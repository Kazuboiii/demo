from django.utils import timezone
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import BusinessUnitScoped

from .models import RideCostEstimate, TransportRequest, Trip
from .serializers import (
    RideCostEstimateSerializer,
    TransportRequestSerializer,
    TripSerializer,
)


class TransportRequestViewSet(viewsets.ModelViewSet):
    queryset = TransportRequest.objects.all().order_by("-created_at")
    serializer_class = TransportRequestSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit=user.business_unit)

    def perform_create(self, serializer):
        user = self.request.user
        bu = serializer.validated_data.get("business_unit") or user.business_unit
        if not user.can_access_business_unit(bu):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Not authorized for this business unit.")
        serializer.save(created_by=user, business_unit=bu)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        if req.status in (TransportRequest.STATUS_COMPLETED, TransportRequest.STATUS_CANCELLED, TransportRequest.STATUS_FAILED):
            return Response({"detail": "Cannot cancel this request."}, status=400)
        req.status = TransportRequest.STATUS_CANCELLED
        req.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Cancelled.", "status": req.status})


class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all().order_by("-created_at")
    serializer_class = TripSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(request__business_unit=user.business_unit)

    def perform_create(self, serializer):
        user = self.request.user
        bu = serializer.validated_data["request"].business_unit
        if not user.can_access_business_unit(bu):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Not authorized for this business unit.")
        with transaction.atomic():
            trip = serializer.save()
            TransportRequest.objects.filter(pk=trip.request_id).update(
                status=TransportRequest.STATUS_ASSIGNED,
                assigned_driver=trip.driver, assigned_vehicle=trip.vehicle,
            )

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        """Advance trip status: assigned->started->picked_up->dropoffed->completed."""
        trip = self.get_object()
        new_status = request.data.get("status")
        order = [
            Trip.STATUS_ASSIGNED, Trip.STATUS_STARTED, Trip.STATUS_PICKED_UP,
            Trip.STATUS_DROPPED_OFF, Trip.STATUS_COMPLETED,
        ]
        try:
            current_idx = order.index(trip.status)
        except ValueError:
            return Response({"detail": "Invalid current status."}, status=400)
        if new_status not in order:
            return Response({"detail": "Invalid status."}, status=400)
        new_idx = order.index(new_status)
        if new_idx != current_idx + 1:
            return Response({"detail": "Invalid status transition."}, status=400)

        now = timezone.now()
        updates = {"status": new_status}
        if new_status == Trip.STATUS_STARTED:
            updates["start_time"] = now
        elif new_status == Trip.STATUS_PICKED_UP:
            updates["pickup_time"] = now
        elif new_status == Trip.STATUS_DROPPED_OFF:
            updates["dropoff_time"] = now
        elif new_status == Trip.STATUS_COMPLETED:
            updates["end_time"] = now
        for k, v in updates.items():
            setattr(trip, k, v)
        trip.save()
        if new_status == Trip.STATUS_COMPLETED:
            TransportRequest.objects.filter(pk=trip.request_id).update(status=TransportRequest.STATUS_COMPLETED)
        return Response(TripSerializer(trip, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def fail(self, request, pk=None):
        trip = self.get_object()
        trip.status = Trip.STATUS_FAILED
        trip.end_time = timezone.now()
        trip.save(update_fields=["status", "end_time", "updated_at"])
        return Response({"detail": "Trip marked failed.", "status": trip.status})


class RideCostEstimateViewSet(viewsets.ModelViewSet):
    """Transport cost estimates. Values come from documented rates, not stock."""

    queryset = RideCostEstimate.objects.all().select_related(
        "business_unit", "transport_request", "trip__request", "created_by"
    )
    serializer_class = RideCostEstimateSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_global_scope:
            return qs
        return qs.filter(business_unit__in=user.accessible_business_units())

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
