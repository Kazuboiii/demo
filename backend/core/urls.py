from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .health import health

from .views import (
    AuthViewSet,
    ApprovedTokenRefreshView,
    BusinessUnitViewSet,
    DepartmentViewSet,
    EmployeeViewSet,
    RoleViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register(r"auth", AuthViewSet, basename="auth")
router.register(r"business-units", BusinessUnitViewSet)
router.register(r"roles", RoleViewSet)
router.register(r"departments", DepartmentViewSet)
router.register(r"users", UserViewSet)
router.register(r"employees", EmployeeViewSet)

urlpatterns = [path("auth/refresh/", ApprovedTokenRefreshView.as_view(), name="token-refresh"), path("health/", health), path("", include(router.urls))]
