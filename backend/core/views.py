from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import BusinessUnit, Department, Employee, Role, User
from .permissions import BusinessUnitScoped, IsAuthenticatedActive, RolePermission, UserAdministrationPermission
from .serializers import (
    BusinessUnitSerializer,
    DepartmentSerializer,
    EmployeeSerializer,
    RoleSerializer,
    UserSerializer,
)

User = get_user_model()


def _tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": UserSerializer(user, context={}).data,
    }


class ApprovedTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = self.token_class(attrs["refresh"])
        user = User.objects.filter(**{
            api_settings.USER_ID_FIELD: token.payload.get(api_settings.USER_ID_CLAIM)
        }).first()
        if user is None or not user.is_active or not user.is_approved:
            raise AuthenticationFailed("Account is unavailable.")
        return super().validate(attrs)


class ApprovedTokenRefreshView(TokenRefreshView):
    serializer_class = ApprovedTokenRefreshSerializer


class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], authentication_classes=[])
    def login(self, request):
        email = request.data.get("email", "")
        password = request.data.get("password", "")
        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.is_active:
            return Response(
                {"detail": "Account is disabled."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.is_approved:
            return Response(
                {"detail": "Account is not approved."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(_tokens_for_user(user))

    @action(detail=False, methods=["get", "post"], authentication_classes=[], url_path="role-login")
    def role_login(self, request):
        from .role_access import ROLE_CHOICES, shared_role_user

        if not settings.ROLE_LOGIN:
            return Response({"detail": "Role access is disabled."}, status=404)
        if request.method == "GET":
            return Response([{"code": code, "name": name} for code, name, _ in ROLE_CHOICES])
        code = request.data.get("role")
        if not isinstance(code, str) or code not in {r[0] for r in ROLE_CHOICES}:
            return Response({"detail": "Choose a valid role."}, status=400)
        user = shared_role_user(code)
        if not user.is_active or not user.is_approved or user.role_code != code:
            return Response({"detail": "This role is currently unavailable."}, status=403)
        return Response(_tokens_for_user(user))

    def _demo_login_allowed(self):
        return bool(getattr(settings, "DEMO_LOGIN", False))

    @action(detail=False, methods=["get"], authentication_classes=[], url_path="demo-accounts")
    def demo_accounts(self, request):
        """List seeded demo accounts for the login-page selector.

        Returns emails, display names and roles only - never passwords - and
        only when demo login is explicitly enabled on this server.
        """
        if not self._demo_login_allowed():
            return Response(
                {"detail": "Demo login is not enabled on this server."},
                status=status.HTTP_404_NOT_FOUND,
            )
        accounts = User.objects.filter(is_demo=True, is_active=True, is_approved=True).order_by(
            "pk"
        )
        data = [
            {
                "email": user.email,
                "name": (user.get_full_name() or user.email).strip(),
                "role_code": user.role_code,
                "role_name": user.role.name if user.role else None,
                "business_unit": user.business_unit_code,
            }
            for user in accounts
        ]
        return Response(data)

    @action(detail=False, methods=["post"], authentication_classes=[], url_path="demo-login")
    def demo_login(self, request):
        """One-click login for seeded demo accounts only.

        Explicitly gated by the DEMO_LOGIN environment setting and the
        per-account `is_demo` flag. It reuses the standard JWT issue path and
        can never reach a regular account (is_demo is False by default).
        """
        if not self._demo_login_allowed():
            return Response(
                {"detail": "Demo login is not enabled on this server."},
                status=status.HTTP_404_NOT_FOUND,
            )
        email = (request.data.get("email") or "").strip().lower()
        user = User.objects.filter(email=email, is_demo=True).first()
        if user is None or not user.is_active or not user.is_approved:
            return Response(
                {"detail": "Demo account is not available."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(_tokens_for_user(user))

    @action(detail=False, methods=["post"], authentication_classes=[])
    def logout(self, request):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                pass
        return Response({"detail": "Logged out."})

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticatedActive])
    def me(self, request):
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticatedActive])
    def workspace(self, request):
        """Division selector metadata for every signed-in role."""
        from .permissions import accessible_divisions, effective_permissions, role_can

        user = request.user
        units = accessible_divisions(user).order_by("name")
        divisions = [
            {
                "id": unit.id,
                "name": unit.name,
                "code": unit.code,
                "is_primary": unit.pk == user.business_unit_id,
                "can_read": role_can(user, "inventory", "read"),
                "can_write": role_can(user, "inventory", "create"),
                "can_approve": role_can(user, "inventory", "approve"),
                "can_export": role_can(user, "inventory", "export"),
            }
            for unit in units
        ]
        default = next(
            (d["id"] for d in divisions if d["is_primary"]),
            divisions[0]["id"] if divisions else None,
        )
        return Response({
            "role": user.role_code,
            "role_name": user.role.name if user.role else None,
            "is_global_scope": user.is_global_scope,
            "organization_overview": user.is_global_scope,
            "default_division": default,
            "divisions": divisions,
            "permissions": effective_permissions(user),
        })


class BusinessUnitViewSet(viewsets.ModelViewSet):
    queryset = BusinessUnit.objects.all().order_by("name")
    serializer_class = BusinessUnitSerializer
    permission_classes = [RolePermission]
    allowed_roles = ("super_admin",)


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all().order_by("name")
    serializer_class = RoleSerializer
    permission_classes = [RolePermission]
    allowed_roles = ("super_admin",)


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all().order_by("business_unit__name", "name")
    serializer_class = DepartmentSerializer
    permission_classes = [BusinessUnitScoped]


    def get_queryset(self):
        from .permissions import accessible_divisions, requested_division

        qs = super().get_queryset()
        unit, error = requested_division(self.request.user, self.request)
        if error is not None:
            raise PermissionDenied(error.data.get("detail", "Not authorized."))
        if unit is not None:
            return qs.filter(business_unit=unit)
        return qs.filter(business_unit__in=accessible_divisions(self.request.user))


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("email")
    serializer_class = UserSerializer
    permission_classes = [BusinessUnitScoped, UserAdministrationPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        # Non-admin roles may see (never manage) only their own account: the
        # 'admin' module requires 'administer' permission, which only
        # super_admin holds in the central matrix.
        return qs.filter(pk=user.pk)


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all().order_by("employee_id")
    serializer_class = EmployeeSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        from .permissions import accessible_divisions, requested_division

        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        unit, error = requested_division(user, self.request)
        if error is not None:
            raise PermissionDenied(error.data.get("detail", "Not authorized."))
        if unit is not None:
            return qs.filter(business_unit=unit)
        return qs.filter(business_unit__in=accessible_divisions(user))
