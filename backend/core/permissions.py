"""
Central authentication/authorization policy.

Two independent controls are enforced everywhere:

1. **Division scope** – which business division (Resort / Healthcare) a record
   belongs to. Inventory managers only ever see their own division; HR, the
   accountant and the super admin may switch divisions.
2. **Action permissions** – a single centralized matrix maps roles to the
   actions they may perform (read, create, update, approve, export, administer)
   per module. A division grant never implies stock-write permission.

Views should use :class:`ModulePermission` and the ``accessible_divisions``
helpers instead of ad-hoc role checks.
"""

from rest_framework import permissions

# ---------------------------------------------------------------------------
# Central permission matrix
# ---------------------------------------------------------------------------

ALL_ACTIONS = frozenset({"read", "create", "update", "approve", "export", "administer"})
READ_EXPORT = frozenset({"read", "export"})
READ_ONLY = frozenset({"read"})

# module -> action -> roles allowed. "*" means every module.
ROLE_PERMISSIONS = {
    "super_admin": {"*": ALL_ACTIONS},
    "healthcare_admin": {
        "*": READ_EXPORT,
        "inventory": ALL_ACTIONS,
        "procurement": ALL_ACTIONS,
        "reports": ALL_ACTIONS,
        "hr": frozenset({"read", "create", "update", "export"}),
        "attendance": frozenset({"read", "create", "update", "approve", "export"}),
    },
    "resort_admin": {
        "*": READ_EXPORT,
        "inventory": ALL_ACTIONS,
        "procurement": ALL_ACTIONS,
        "reports": ALL_ACTIONS,
        "hr": frozenset({"read", "create", "update", "export"}),
        "attendance": frozenset({"read", "create", "update", "approve", "export"}),
    },
    "healthcare_inventory_manager": {
        "inventory": frozenset({"read", "create", "update", "approve", "export"}),
        "procurement": frozenset({"read", "create", "update", "export"}),
        "reports": READ_EXPORT,
    },
    "resort_inventory_manager": {
        "inventory": frozenset({"read", "create", "update", "approve", "export"}),
        "procurement": frozenset({"read", "create", "update", "export"}),
        "reports": READ_EXPORT,
    },
    # Legacy role retained for existing accounts/tests.
    "inventory_manager": {
        "inventory": frozenset({"read", "create", "update", "approve", "export"}),
        "procurement": frozenset({"read", "create", "update", "export"}),
        "reports": READ_EXPORT,
    },
    "hr_manager": {
        "inventory": READ_EXPORT,  # read-only unless explicitly granted more
        "procurement": READ_EXPORT,
        "reports": READ_EXPORT,
        "hr": frozenset({"read", "create", "update", "approve", "export"}),
        "attendance": frozenset({"read", "create", "update", "approve", "export"}),
        "payroll": frozenset({"read", "create", "update", "approve", "export"}),
    },
    "accountant": {
        "inventory": READ_EXPORT,
        "procurement": frozenset({"read", "create", "update", "approve", "export"}),
        "finance": ALL_ACTIONS,
        "reports": READ_EXPORT,
    },
    "fleet_manager": {
        "fleet": ALL_ACTIONS,
        "transport": frozenset({"read", "create", "update", "approve", "export"}),
        "reports": READ_EXPORT,
    },
    "driver": {
        "fleet": READ_ONLY,
        "transport": READ_ONLY,
        "attendance": frozenset({"read", "create"}),
        "inventory": READ_ONLY,
    },
    "employee": {
        "attendance": frozenset({"read", "create"}),
        "reports": READ_ONLY,
    },
}

GLOBAL_ROLES = frozenset({"super_admin", "hr_manager", "accountant"})


def role_can(user, module, action):
    """Return True when *user* may perform *action* on *module*."""
    if not user or not user.is_authenticated or not user.is_active or not user.is_approved:
        return False
    if user.is_superuser:
        return True
    code = user.role_code
    if not code:
        return False
    rules = ROLE_PERMISSIONS.get(code)
    if not rules:
        return False
    wildcard = rules.get("*", frozenset())
    if action in wildcard:
        return True
    return action in rules.get(module, frozenset())


def effective_permissions(user):
    """Serializable permission matrix for the signed-in user."""
    modules = ["inventory", "procurement", "finance", "hr", "attendance", "payroll",
               "transport", "fleet", "reports", "admin"]
    result = {}
    for module in modules:
        result[module] = sorted(
            action for action in ALL_ACTIONS if role_can(user, module, action)
        )
    return result


def accessible_divisions(user):
    """Business divisions the user may read. Never raises."""
    if not user or not user.is_authenticated:
        from core.models import BusinessUnit

        return BusinessUnit.objects.none()
    return user.accessible_business_units()


def requested_division(user, request, required_action="read"):
    """Resolve and authorize the division for a request.

    Accepts ``business_unit`` (id or code) or ``division`` (code). Returns
    ``(business_unit, error_response)``. A missing selector is allowed for
    users with exactly one accessible division.
    """
    from core.models import BusinessUnit
    from rest_framework.response import Response

    units = accessible_divisions(user)
    raw = (
        request.query_params.get("business_unit")
        or request.query_params.get("division")
        or (request.data.get("business_unit") if hasattr(request, "data") else None)
        or (request.data.get("division") if hasattr(request, "data") else None)
    )
    if raw in (None, "", "all", "ALL"):
        count = units.count()
        if count == 1:
            return units.first(), None
        if count == 0:
            return None, Response({"detail": "No business division is available."}, status=403)
        return None, None  # explicit "all accessible" aggregate

    try:
        unit = BusinessUnit.objects.get(pk=int(raw))
    except (ValueError, TypeError):
        unit = BusinessUnit.objects.filter(code__iexact=str(raw)).first()
    except BusinessUnit.DoesNotExist:
        unit = BusinessUnit.objects.filter(code__iexact=str(raw)).first()

    if unit is None:
        return None, Response({"detail": "Business division not found."}, status=404)
    if not units.filter(pk=unit.pk).exists():
        return None, Response(
            {"detail": "You are not authorized for this business division."},
            status=403,
        )
    return unit, None


def scoped_queryset(qs, user, field="business_unit"):
    """Filter a queryset to the divisions a user may access."""
    if not user or not user.is_authenticated:
        return qs.none()
    if user.is_global_scope:
        return qs
    return qs.filter(**{f"{field}__in": accessible_divisions(user)})


# ---------------------------------------------------------------------------
# DRF permission classes
# ---------------------------------------------------------------------------


class IsAuthenticatedActive(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and bool(
            request.user and request.user.is_active and request.user.is_approved
        )


class BusinessUnitScoped(permissions.BasePermission):
    """
    Object-level permission: user may only access objects whose business unit
    is one of their accessible divisions.
    """

    business_unit_field = "business_unit"

    def _is_global(self, user):
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.has_role("super_admin"))
        )

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_active and user.is_approved)

    def _unit_of(self, obj):
        field = self.business_unit_field
        if hasattr(obj, field):
            return getattr(obj, field)
        if hasattr(obj, "get_business_unit"):
            return obj.get_business_unit()
        for relation in ("product", "product_batch", "vehicle", "employee", "request", "user"):
            parent = getattr(obj, relation, None)
            if parent is not None:
                unit = self._unit_of(parent)
                if unit is not None:
                    return unit
        return None

    def has_object_permission(self, request, view, obj):
        unit = self._unit_of(obj)
        if unit is None:
            return False
        return request.user.can_access_business_unit(unit)


class ModulePermission(permissions.BasePermission):
    """Enforce the centralized role/action matrix.

    Views set ``module`` and may set ``action_map`` mapping HTTP methods to
    matrix actions. Custom viewset actions can set ``required_action`` on the
    view before dispatch (see :class:`InventoryActionPermission`).
    """

    module = "reports"
    default_action = "read"
    action_map = {
        "GET": "read",
        "HEAD": "read",
        "OPTIONS": "read",
        "POST": "create",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "administer",
    }

    def has_permission(self, request, view):
        if not IsAuthenticatedActive().has_permission(request, view):
            return False
        module = getattr(view, "module", self.module)
        action = getattr(view, "required_action", None) or self.action_map.get(
            request.method, self.default_action
        )
        return role_can(request.user, module, action)


class RolePermission(permissions.BasePermission):
    """Allow only listed role codes (kept for backwards compatibility)."""

    allowed_roles = ()

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.has_role("super_admin"):
            return True
        return user.role_code in getattr(view, "allowed_roles", self.allowed_roles)
