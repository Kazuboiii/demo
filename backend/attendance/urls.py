from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AttendanceCorrectionRequestViewSet,
    AttendanceEventViewSet,
    LeaveRequestViewSet,
    OneTimeQRTokenViewSet,
    RotatingQRViewSet,
    ShiftViewSet,
)

router = DefaultRouter()
router.register(r"shifts", ShiftViewSet)
router.register(r"events", AttendanceEventViewSet)
router.register(r"rotating-qr", RotatingQRViewSet, basename="rotating-qr")
router.register(r"one-time-qr", OneTimeQRTokenViewSet, basename="one-time-qr")
router.register(r"leave-requests", LeaveRequestViewSet)
router.register(r"correction-requests", AttendanceCorrectionRequestViewSet)

urlpatterns = [path("", include(router.urls))]
