from django.db import transaction
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core.permissions import BusinessUnitScoped

from .models import (
    RideAssignment,
    RideFareEstimate,
    RideRecord,
    RideRequest,
    RideCostEstimate,
    TransportRequest,
    Trip,
    VehicleMaintenanceRecord,
    TransportationExpense,
)
from .serializers import (
    RideAssignmentSerializer,
    RideFareEstimateSerializer,
    RideRecordSerializer,
    RideRequestSerializer,
    RideCostEstimateSerializer,
    TransportationExpenseSerializer,
    TransportRequestSerializer,
    TripSerializer,
    VehicleMaintenanceRecordSerializer,
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


# ---------------------------------------------------------------------------
# Ride management views
# ---------------------------------------------------------------------------


class RideRequestViewSet(viewsets.ModelViewSet):
    queryset = RideRequest.objects.all().order_by("-requested_at")
    serializer_class = RideRequestSerializer
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
        ride = self.get_object()
        if ride.status in (RideRequest.STATUS_COMPLETED, RideRequest.STATUS_CANCELLED, RideRequest.STATUS_FAILED):
            return Response({"detail": "Cannot cancel this ride."}, status=400)
        ride.status = RideRequest.STATUS_CANCELLED
        ride.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Ride cancelled.", "status": ride.status})

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        ride = self.get_object()
        if ride.status != RideRequest.STATUS_REQUESTED:
            return Response({"detail": "Only requested rides can be assigned."}, status=400)
        serializer = RideAssignmentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save()
        ride.assigned_driver = assignment.driver
        ride.assigned_vehicle = assignment.vehicle
        ride.status = RideRequest.STATUS_ASSIGNED
        ride.save(update_fields=["assigned_driver", "assigned_vehicle", "status", "updated_at"])
        return Response(RideRequestSerializer(ride, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def start_ride(self, request, pk=None):
        ride = self.get_object()
        if ride.status != RideRequest.STATUS_ASSIGNED:
            return Response({"detail": "Only assigned rides can start."}, status=400)
        trip = ride.ride_trip
        if trip is None:
            driver = ride.assigned_driver
            vehicle = ride.assigned_vehicle
            if driver is None or vehicle is None:
                return Response({"detail": "Ride has no driver or vehicle assigned."}, status=400)
            trip = Trip.objects.create(
                request=ride,
                driver=driver,
                vehicle=vehicle,
                status=Trip.STATUS_STARTED,
                start_time=timezone.now(),
            )
            ride.ride_trip = trip
        else:
            if trip.status != Trip.STATUS_STARTED:
                return Response({"detail": "Linked trip has not started."}, status=400)
        ride.status = RideRequest.STATUS_IN_PROGRESS
        ride.save(update_fields=["status", "updated_at"])
        return Response(RideRequestSerializer(ride, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def complete_ride(self, request, pk=None):
        ride = self.get_object()
        if ride.status != RideRequest.STATUS_IN_PROGRESS:
            return Response({"detail": "Only in-progress rides can complete."}, status=400)
        trip = ride.ride_trip
        if trip is None:
            return Response({"detail": "Ride has no linked trip."}, status=400)
        if trip.status != Trip.STATUS_PICKED_UP:
            return Response({"detail": "Trip must be picked up before completing."}, status=400)
        trip.status = Trip.STATUS_COMPLETED
        trip.end_time = timezone.now()
        trip.save(update_fields=["status", "end_time", "updated_at"])
        ride.status = RideRequest.STATUS_COMPLETED
        ride.save(update_fields=["status", "updated_at"])
        RideRecord.objects.update_or_create(
            ride_request=ride,
            defaults={
                "driver": trip.driver,
                "vehicle": trip.vehicle,
                "status": RideRequest.STATUS_COMPLETED,
                "pickup_time": trip.pickup_time,
                "dropoff_time": trip.dropoff_time,
                "completed_at": trip.end_time,
                "notes": trip.notes,
            },
        )
        return Response(RideRequestSerializer(ride, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def fail_ride(self, request, pk=None):
        ride = self.get_object()
        if ride.status not in (RideRequest.STATUS_ASSIGNED, RideRequest.STATUS_IN_PROGRESS):
            return Response({"detail": "Cannot fail this ride."}, status=400)
        ride.status = RideRequest.STATUS_FAILED
        ride.save(update_fields=["status", "updated_at"])
        return Response(RideRequestSerializer(ride, context={"request": request}).data)


class RideAssignmentViewSet(viewsets.ModelViewSet):
    queryset = RideAssignment.objects.all().order_by("-assigned_at")
    serializer_class = RideAssignmentSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(ride_request__business_unit=user.business_unit)


class RideRecordViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RideRecord.objects.all().order_by("-completed_at", "-created_at")
    serializer_class = RideRecordSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(ride_request__business_unit=user.business_unit)


class RideFareEstimateViewSet(viewsets.ModelViewSet):
    queryset = RideFareEstimate.objects.all().select_related(
        "business_unit", "ride_request", "trip__request", "created_by"
    )
    serializer_class = RideFareEstimateSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit__in=user.accessible_business_units())

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def share(self, request, pk=None):
        fare = self.get_object()
        if fare.fare_status != RideFareEstimate.STATUS_DRAFT:
            return Response({"detail": "Only draft fare estimates can be shared."}, status=400)
        fare.fare_status = RideFareEstimate.STATUS_SHARED
        fare.save(update_fields=["fare_status", "updated_at"])
        fare.refresh_from_db()
        return Response(RideFareEstimateSerializer(fare, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        fare = self.get_object()
        if fare.fare_status != RideFareEstimate.STATUS_SHARED:
            return Response({"detail": "Only shared fare estimates can be accepted."}, status=400)
        fare.fare_status = RideFareEstimate.STATUS_ACCEPTED
        fare.save(update_fields=["fare_status", "updated_at"])
        fare.refresh_from_db()
        return Response(RideFareEstimateSerializer(fare, context={"request": request}).data)


class VehicleMaintenanceRecordViewSet(viewsets.ModelViewSet):
    queryset = VehicleMaintenanceRecord.objects.all().order_by("-service_date", "-created_at")
    serializer_class = VehicleMaintenanceRecordSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit=user.business_unit)


class TransportationExpenseViewSet(viewsets.ModelViewSet):
    queryset = TransportationExpense.objects.all().order_by("-created_at")
    serializer_class = TransportationExpenseSerializer
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
        serializer.save(submitted_by=self.request.user)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        expense = self.get_object()
        if expense.status != TransportationExpense.STATUS_DRAFT:
            return Response({"detail": "Only draft expenses can be approved."}, status=400)
        expense.status = TransportationExpense.STATUS_APPROVED
        expense.approved_by = request.user
        expense.approved_at = timezone.now()
        expense.save(update_fields=["status", "approved_by", "approved_at"])
        return Response(TransportationExpenseSerializer(expense, context={"request": request}).data)
