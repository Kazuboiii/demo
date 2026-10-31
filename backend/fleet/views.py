from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import BusinessUnitScoped

from .models import DriverProfile, GPSPosition, TrackingDevice, Vehicle, VehicleAssignment
from .serializers import (
    DriverProfileSerializer, GPSPositionSerializer, TrackingDeviceSerializer,
    VehicleAssignmentSerializer, VehicleSerializer,
)


class VehicleViewSet(viewsets.ModelViewSet):
    queryset = Vehicle.objects.all().order_by("license_plate")
    serializer_class = VehicleSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit=user.business_unit)

    @action(detail=False, methods=["get"])
    def available(self, request):
        qs = self.get_queryset().filter(status=Vehicle.STATUS_AVAILABLE)
        return Response(VehicleSerializer(qs, many=True, context={"request": request}).data)


class DriverProfileViewSet(viewsets.ModelViewSet):
    queryset = DriverProfile.objects.all().order_by("user__email")
    serializer_class = DriverProfileSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(user__business_unit=user.business_unit)


class VehicleAssignmentViewSet(viewsets.ModelViewSet):
    queryset = VehicleAssignment.objects.all().order_by("-assigned_at")
    serializer_class = VehicleAssignmentSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(vehicle__business_unit=user.business_unit)

    def perform_create(self, serializer):
        assignment = serializer.save()
        if not assignment.is_active:
            return
        assignment.vehicle.status = Vehicle.STATUS_IN_USE
        assignment.vehicle.save(update_fields=["status"])

    def perform_update(self, serializer):
        assignment = serializer.save()
        if assignment.returned_at and assignment.vehicle.status == Vehicle.STATUS_IN_USE:
            # check no other active assignment keeps it in use
            still_active = VehicleAssignment.objects.filter(
                vehicle=assignment.vehicle, returned_at__isnull=True
            ).exists()
            if not still_active:
                assignment.vehicle.status = Vehicle.STATUS_AVAILABLE
                assignment.vehicle.save(update_fields=["status"])


class TrackingDeviceViewSet(viewsets.ModelViewSet):
    queryset = TrackingDevice.objects.all().order_by("device_id")
    serializer_class = TrackingDeviceSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(vehicle__business_unit=user.business_unit)


class GPSPositionViewSet(viewsets.ModelViewSet):
    queryset = GPSPosition.objects.all().order_by("-recorded_at")
    serializer_class = GPSPositionSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(vehicle__business_unit=user.business_unit)

    def perform_create(self, serializer):
        serializer.save(vehicle=serializer.validated_data.get("vehicle"))
