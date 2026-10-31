"""
Non-Emergency Medical Transportation (NEMT) and ride management.

Fictional transport workflow:
pending -> assigned -> started -> picked_up -> dropoffed -> completed,
with cancellation / failed-pickup branches.

Ride management models reuse the existing vehicle/driver/fleet foundation and
add ride requests, ride assignments, ride records, ride fare estimates, ride
statuses, vehicle maintenance records, and transportation expenses.
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
    passenger_name = models.CharField(max_length=150, default="")
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


# ---------------------------------------------------------------------------
# Transportation and ride management
# ---------------------------------------------------------------------------


class RideRequest(models.Model):
    """Ride request record for transportation and ride management."""

    STATUS_REQUESTED = "requested"
    STATUS_ASSIGNED = "assigned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Failed"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="ride_requests"
    )
    rider_name = models.CharField(max_length=150)
    pickup_location = models.CharField(max_length=250)
    dropoff_location = models.CharField(max_length=250)
    requested_at = models.DateTimeField(default=timezone.now)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ride_requests",
    )
    assigned_driver = models.ForeignKey(
        DriverProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ride_assignments",
    )
    assigned_vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ride_assignments",
    )
    ride_trip = models.OneToOneField(
        Trip, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ride_request",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = "Ride Request"
        verbose_name_plural = "Ride Requests"
        indexes = [models.Index(fields=["business_unit", "-requested_at"])]

    def __str__(self):
        return self.reference


class RideAssignment(models.Model):
    """Assignment linking a ride request to a driver/vehicle."""

    ride_request = models.OneToOneField(
        RideRequest, on_delete=models.CASCADE, related_name="assignment"
    )
    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="ride_assignments_meta")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="ride_assignments_meta")
    assigned_at = models.DateTimeField(default=timezone.now)
    accepted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-assigned_at"]
        verbose_name = "Ride Assignment"
        verbose_name_plural = "Ride Assignments"

    def __str__(self):
        return f"{self.ride_request.reference} -> {self.driver.user.email}"


class RideRecord(models.Model):
    """Persisted ride history record for reporting."""

    ride_request = models.OneToOneField(
        RideRequest, on_delete=models.CASCADE, related_name="ride_record"
    )
    driver = models.ForeignKey(DriverProfile, on_delete=models.PROTECT, related_name="ride_records")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="ride_records")
    status = models.CharField(max_length=20, choices=RideRequest.STATUS_CHOICES)
    pickup_time = models.DateTimeField(null=True, blank=True)
    dropoff_time = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-completed_at", "-created_at"]
        verbose_name = "Ride Record"
        verbose_name_plural = "Ride Records"
        indexes = [models.Index(fields=["ride_request", "-completed_at"])]

    def get_business_unit(self):
        return self.ride_request.business_unit

    def __str__(self):
        return f"Ride {self.ride_request.reference} - {self.status}"


class RideFareEstimate(models.Model):
    """Ride fare estimate with fare status and trip linkage."""

    STATUS_DRAFT = "draft"
    STATUS_SHARED = "shared"
    STATUS_ACCEPTED = "accepted"
    STATUS_USED = "used"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SHARED, "Shared"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_USED, "Used"),
        (STATUS_EXPIRED, "Expired"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="ride_fare_estimates"
    )
    ride_request = models.OneToOneField(
        RideRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fare_estimate",
    )
    trip = models.OneToOneField(
        Trip, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fare_estimate",
    )
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    duration_minutes = models.PositiveIntegerField(default=0)
    base_fare = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    per_km_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    per_minute_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tolls = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_fare = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="NPR")
    fare_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ride_fare_estimates",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Ride Fare Estimate"
        verbose_name_plural = "Ride Fare Estimates"
        indexes = [
            models.Index(fields=["business_unit", "-created_at"]),
            models.Index(fields=["ride_request", "fare_status"]),
        ]

    def calculate_estimated_fare(self):
        from decimal import Decimal

        hours = Decimal(self.duration_minutes or 0) / Decimal("60")
        distance_cost = (self.distance_km or Decimal("0")) * (self.per_km_rate or Decimal("0"))
        duration_cost = hours * (self.per_minute_rate or Decimal("0"))
        return (
            (self.base_fare or Decimal("0"))
            + distance_cost
            + duration_cost
            + (self.tolls or Decimal("0"))
        ).quantize(Decimal("0.01"))

    def clean(self):
        if self.ride_request_id and (
            self.ride_request.business_unit_id != self.business_unit_id
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError("Ride fare estimate ride request must belong to the same division.")
        if self.trip_id and self.trip.request.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Ride fare estimate trip must belong to the same division.")

    def save(self, *args, **kwargs):
        self.estimated_fare = self.calculate_estimated_fare()
        return super().save(*args, **kwargs)


class VehicleMaintenanceRecord(models.Model):
    """Vehicle maintenance records for transportation expenses."""

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="maintenance_records")
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="vehicle_maintenance_records"
    )
    maintenance_type = models.CharField(max_length=60)
    description = models.TextField(blank=True, default="")
    cost = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Maintenance cost, stored precisely as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")
    service_date = models.DateField()
    completed_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="vehicle_maintenance_records",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-service_date", "-created_at"]
        verbose_name = "Vehicle Maintenance Record"
        verbose_name_plural = "Vehicle Maintenance Records"
        indexes = [models.Index(fields=["business_unit", "-service_date"])]

    def clean(self):
        if self.vehicle_id and self.vehicle.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Maintenance record vehicle must belong to the same division.")

    def __str__(self):
        return f"{self.vehicle.license_plate} {self.service_date}"


class TransportationExpense(models.Model):
    """Transportation expense record."""

    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PAID, "Paid"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="transportation_expenses"
    )
    expense_type = models.CharField(max_length=50)
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transportation_expenses",
    )
    driver = models.ForeignKey(
        DriverProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transportation_expenses",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Transportation expense amount, stored precisely as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="submitted_transportation_expenses",
    )
    approved_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_transportation_expenses",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Transportation Expense"
        verbose_name_plural = "Transportation Expenses"
        indexes = [models.Index(fields=["business_unit", "-created_at"])]

    def clean(self):
        if self.vehicle_id and self.vehicle.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Transportation expense vehicle must belong to the same division.")
        if self.driver_id and self.driver.user.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Transportation expense driver must belong to the same division.")

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency}"
