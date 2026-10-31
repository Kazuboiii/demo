from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DriverProfileViewSet,
    GPSPositionViewSet,
    TrackingDeviceViewSet,
    VehicleAssignmentViewSet,
    VehicleViewSet,
)

router = DefaultRouter()
router.register(r"vehicles", VehicleViewSet)
router.register(r"drivers", DriverProfileViewSet)
router.register(r"assignments", VehicleAssignmentViewSet)
router.register(r"tracking-devices", TrackingDeviceViewSet)
router.register(r"gps-positions", GPSPositionViewSet)

urlpatterns = [path("", include(router.urls))]
