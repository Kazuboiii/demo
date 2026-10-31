from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import BusinessUnit, Department, Employee, Role, User
from .permissions import BusinessUnitScoped, IsAuthenticatedActive, RolePermission
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


class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"])
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

    @action(detail=False, methods=["post"])
    def logout(self, request):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
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
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit=user.business_unit)


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
