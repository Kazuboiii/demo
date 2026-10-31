"""
Fleet management: vehicles, drivers, assignments, tracking devices, GPS telemetry.

Vehicles belong to a business unit. Exclusive vehicle assignments cannot overlap
(an assignment is active until its `returned_at` is set).
"""

from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import BusinessUnit, Employee


class Vehicle(models.Model):
    STATUS_AVAILABLE = "available"
    STATUS_IN_USE = "in_use"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_IN_USE, "In Use"),
        (STATUS_MAINTENANCE, "Maintenance"),
    ]

    license_plate = models.CharField(max_length=30, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="vehicles"
    )
    make = models.CharField(max_length=80, blank=True, default="")
    model = models.CharField(max_length=80, blank=True, default="")
    year = models.PositiveIntegerField(null=True, blank=True)
    capacity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    maintenance_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["license_plate"]
        verbose_name = "Vehicle"
        verbose_name_plural = "Vehicles"

    def __str__(self):
        return self.license_plate

    def is_available(self):
        return self.status == self.STATUS_AVAILABLE


class DriverProfile(models.Model):
    user = models.OneToOneField(
        "core.User", on_delete=models.CASCADE, related_name="driver_profile"
    )
    license_number = models.CharField(max_length=50, blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Driver Profile"
        verbose_name_plural = "Driver Profiles"

    def __str__(self):
        return self.user.get_full_name() or self.user.email


class VehicleAssignment(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="assignments")
    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="assignments")
    assigned_at = models.DateTimeField(default=timezone.now)
    returned_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-assigned_at"]
        verbose_name = "Vehicle Assignment"
        verbose_name_plural = "Vehicle Assignments"

    def __str__(self):
        return f"{self.vehicle.license_plate} -> {self.driver.user.email}"

    @property
    def is_active(self):
        return self.returned_at is None

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.is_active:
            overlap = VehicleAssignment.objects.filter(
                vehicle=self.vehicle, returned_at__isnull=True
            ).exclude(pk=self.pk)
            if overlap.exists():
                raise ValidationError(
                    "This vehicle already has an active assignment."
                )
        overlap_driver = VehicleAssignment.objects.filter(
            driver=self.driver, returned_at__isnull=True
        ).exclude(pk=self.pk)
        if overlap_driver.exists():
            raise ValidationError("This driver already has an active assignment.")


class TrackingDevice(models.Model):
    device_id = models.CharField(max_length=60, unique=True)
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="tracking_devices"
    )
    is_connected = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Tracking Device"
        verbose_name_plural = "Tracking Devices"

    def __str__(self):
        return self.device_id


class GPSPosition(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="positions")
    latitude = models.FloatField()
    longitude = models.FloatField()
    recorded_at = models.DateTimeField(default=timezone.now)
    simulated = models.BooleanField(
        default=True, help_text="True for simulator-generated telemetry."
    )
    speed = models.FloatField(null=True, blank=True)
    trip = models.ForeignKey(
        "nemt.Trip", on_delete=models.SET_NULL, null=True, blank=True, related_name="gps_positions"
    )

    class Meta:
        ordering = ["-recorded_at"]
        verbose_name = "GPS Position"
        verbose_name_plural = "GPS Positions"
        indexes = [
            models.Index(fields=["vehicle", "-recorded_at"]),
        ]

    def __str__(self):
        return f"{self.vehicle.license_plate} @ {self.recorded_at}"
