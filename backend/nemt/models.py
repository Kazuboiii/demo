"""
Non-Emergency Medical Transportation (NEMT).

Fictional patient transport workflow:
pending -> assigned -> started -> picked_up -> dropoffed -> completed,
with cancellation / failed-pickup branches.
"""

from django.db import models
from django.utils import timezone

from core.models import BusinessUnit
from fleet.models import DriverProfile, Vehicle


class TransportRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ASSIGNED = "assigned"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Failed"),
    ]

    reference = models.CharField(max_length=40, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="nemt_requests"
    )
    patient_name = models.CharField(max_length=150)
    pickup_location = models.CharField(max_length=250)
    dropoff_location = models.CharField(max_length=250)
    pickup_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="nemt_requests"
    )
    assigned_driver = models.ForeignKey(
        DriverProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="nemt_requests"
    )
    assigned_vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name="nemt_requests"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Transport Request"
        verbose_name_plural = "Transport Requests"

    def __str__(self):
        return self.reference


class Trip(models.Model):
    STATUS_ASSIGNED = "assigned"
    STATUS_STARTED = "started"
    STATUS_PICKED_UP = "picked_up"
    STATUS_DROPPED_OFF = "dropoffed"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_STARTED, "Started"),
        (STATUS_PICKED_UP, "Picked Up"),
        (STATUS_DROPPED_OFF, "Dropped Off"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Failed"),
    ]

    request = models.OneToOneField(
        TransportRequest, on_delete=models.CASCADE, related_name="trip"
    )
    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="trips")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="trips")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ASSIGNED)
    start_time = models.DateTimeField(null=True, blank=True)
    pickup_time = models.DateTimeField(null=True, blank=True)
    dropoff_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Trip"
        verbose_name_plural = "Trips"

    def __str__(self):
        return f"Trip {self.request.reference} - {self.status}"


class RideCostEstimate(models.Model):
    """Transport cost estimate derived from trip inputs, never from inventory.

    The total is computed from the documented rates on this record so finance
    and management reports can reconcile every figure.
    """

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="ride_cost_estimates"
    )
    transport_request = models.ForeignKey(
        TransportRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cost_estimates",
    )
    trip = models.OneToOneField(
        Trip, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cost_estimate",
    )
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    duration_minutes = models.PositiveIntegerField(default=0)
    base_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    per_km_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    driver_hourly_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tolls = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="NPR")
    notes = models.CharField(max_length=250, blank=True, default="")
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ride_cost_estimates",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Ride Cost Estimate"
        verbose_name_plural = "Ride Cost Estimates"
        indexes = [models.Index(fields=["business_unit", "-created_at"])]

    def __str__(self):
        return f"{self.reference} ({self.total_cost} {self.currency})"

    def calculate_total(self):
        from decimal import Decimal

        hours = Decimal(self.duration_minutes or 0) / Decimal("60")
        return (
            (self.base_fee or Decimal("0"))
            + (self.distance_km or Decimal("0")) * (self.per_km_rate or Decimal("0"))
            + hours * (self.driver_hourly_rate or Decimal("0"))
            + (self.tolls or Decimal("0"))
        ).quantize(Decimal("0.01"))

    def clean(self):
        if self.transport_request_id and (
            self.transport_request.business_unit_id != self.business_unit_id
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError("The transport request must belong to the same division.")
        if self.trip_id and self.trip.request.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("The trip must belong to the same division.")

    def save(self, *args, **kwargs):
        self.total_cost = self.calculate_total()
        return super().save(*args, **kwargs)
