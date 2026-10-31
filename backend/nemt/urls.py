from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    RideAssignmentViewSet,
    RideCostEstimateViewSet,
    RideFareEstimateViewSet,
    RideRecordViewSet,
    RideRequestViewSet,
    TransportationExpenseViewSet,
    TransportRequestViewSet,
    TripViewSet,
    VehicleMaintenanceRecordViewSet,
)

router = DefaultRouter()
router.register(r"requests", TransportRequestViewSet)
router.register(r"trips", TripViewSet)
router.register(r"cost-estimates", RideCostEstimateViewSet)
router.register(r"ride-requests", RideRequestViewSet)
router.register(r"ride-assignments", RideAssignmentViewSet)
router.register(r"ride-records", RideRecordViewSet)
router.register(r"ride-fare-estimates", RideFareEstimateViewSet)
router.register(r"vehicle-maintenance", VehicleMaintenanceRecordViewSet)
router.register(r"transportation-expenses", TransportationExpenseViewSet)

urlpatterns = [path("", include(router.urls))]
