"""
Shared attendance engine for healthcare and resort staff.

Authoritative record: AttendanceEvent (check-in / check-out events).
Two QR modes:
- RotatingQRToken: shared workplace QR, valid 30s, redeemable once per
  employee/action/shift during its validity window.
- OneTimeQRToken: employee-specific single-use QR, default 5 minutes.
"""

from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import BusinessUnit, Department, Employee


class Shift(models.Model):
    name = models.CharField(max_length=100)  # e.g. "Morning", "Night", "Flex"
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="shifts"
    )
    start_time = models.TimeField()  # HH:MM
    end_time = models.TimeField()
    overnight = models.BooleanField(
        default=False,
        help_text="True if the shift crosses midnight (end_time < start_time).",
    )
    grace_minutes = models.PositiveIntegerField(
        default=15,
        help_text="Grace period (minutes) before a check-in is marked late.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["business_unit__name", "name"]
        unique_together = [("name", "business_unit")]
        verbose_name = "Shift"
        verbose_name_plural = "Shifts"

    def __str__(self):
        return f"{self.business_unit.name} - {self.name}"

    def is_overnight(self):
        return self.overnight


class AttendanceEvent(models.Model):
    ACTION_CHECK_IN = "check_in"
    ACTION_CHECK_OUT = "check_out"
    ACTION_CHOICES = [(ACTION_CHECK_IN, "Check In"), (ACTION_CHECK_OUT, "Check Out")]

    SOURCE_MANUAL = "manual"
    SOURCE_QR_ROTATING = "qr_rotating"
    SOURCE_QR_ONE_TIME = "qr_one_time"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_QR_ROTATING, "Rotating QR"),
        (SOURCE_QR_ONE_TIME, "One-Time QR"),
    ]

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="attendance_events"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="attendance_events"
    )
    shift = models.ForeignKey(
        Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField()
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp", "-created_at"]
        verbose_name = "Attendance Event"
        verbose_name_plural = "Attendance Events"
        indexes = [
            models.Index(fields=["employee", "action", "timestamp"]),
            models.Index(fields=["business_unit", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.employee.employee_id} {self.action} @ {self.timestamp}"


class RotatingQRToken(models.Model):
    """Shared workplace QR. Regenerated every 30 seconds by the workplace display."""

    token = models.CharField(max_length=64, unique=True, db_index=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="rotating_qr_tokens"
    )
    action = models.CharField(max_length=20, choices=AttendanceEvent.ACTION_CHOICES)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]
        verbose_name = "Rotating QR Token"
        verbose_name_plural = "Rotating QR Tokens"

    def __str__(self):
        return f"{self.business_unit.code} {self.action} {self.token[:8]}..."

    def is_expired(self, now=None):
        now = now or timezone.now()
        return now >= self.expires_at or not self.is_active

    @classmethod
    def current_for(cls, business_unit, action, now=None):
        """Return the active, non-expired token for a unit/action, creating one
        if needed. Called by the QR display endpoint."""
        now = now or timezone.now()
        token = (
            cls.objects.filter(business_unit=business_unit, action=action, is_active=True)
            .filter(expires_at__gt=now)
            .order_by("-issued_at")
            .first()
        )
        if token is None:
            import secrets
            from datetime import timedelta

            token = cls.objects.create(
                business_unit=business_unit,
                action=action,
                token=secrets.token_urlsafe(24),
                issued_at=now,
                expires_at=now + timedelta(seconds=settings.ROTATING_QR_VALIDITY_SECONDS),
                is_active=True,
            )
        return token


class RotatingQRRedemption(models.Model):
    """Tracks that an employee redeemed a rotating QR for a given action.

    A rotating QR is shared: different employees may redeem the same token,
    but the same employee/action may redeem it only once.
    """

    token = models.ForeignKey(
        RotatingQRToken, on_delete=models.CASCADE, related_name="redemptions"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="rotating_qr_redemptions"
    )
    action = models.CharField(max_length=20, choices=AttendanceEvent.ACTION_CHOICES)
    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-redeemed_at"]
        unique_together = [("token", "employee", "action")]
        verbose_name = "Rotating QR Redemption"
        verbose_name_plural = "Rotating QR Redemptions"

    def __str__(self):
        return f"{self.employee.employee_id} redeemed {self.token.token[:8]} ({self.action})"


class OneTimeQRToken(models.Model):
    """Employee-specific single-use attendance QR."""

    STATUS_ACTIVE = "active"
    STATUS_USED = "used"
    STATUS_EXPIRED = "expired"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_USED, "Used"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_REVOKED, "Revoked"),
    ]

    token = models.CharField(max_length=64, unique=True, db_index=True)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="one_time_qr_tokens"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="one_time_qr_tokens"
    )
    action = models.CharField(max_length=20, choices=AttendanceEvent.ACTION_CHOICES)
    issued_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="issued_qr_tokens"
    )
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "One-Time QR Token"
        verbose_name_plural = "One-Time QR Tokens"
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["business_unit", "status", "expires_at"]),
        ]

    def __str__(self):
        return f"{self.token[:8]}... {self.status}"

    def is_valid_for(self, employee, now=None):
        now = now or timezone.now()
        if self.status != self.STATUS_ACTIVE:
            return False, "token-not-active"
        if now >= self.expires_at:
            return False, "token-expired"
        if self.employee_id != employee.pk:
            return False, "wrong-employee"
        if self.business_unit_id != employee.business_unit_id:
            return False, "wrong-workplace"
        return True, ""

    def redeem(self, employee, now=None):
        from django.db import transaction

        with transaction.atomic():
            # Acquire the employee write lock before reading attendance/token state.
            # Unlike select_for_update(), this also serializes writers on SQLite.
            Employee.objects.filter(pk=employee.pk).update(is_active=models.F("is_active"))
            self.refresh_from_db()
            now = now or timezone.now()
            ok, reason = self.is_valid_for(employee, now=now)
            if not ok:
                return False, reason
            last = AttendanceEvent.objects.filter(employee=employee).order_by("-timestamp", "-pk").first()
            checked_in = last is not None and last.action == AttendanceEvent.ACTION_CHECK_IN
            if self.action == AttendanceEvent.ACTION_CHECK_IN and checked_in:
                return False, "already-checked-in"
            if self.action == AttendanceEvent.ACTION_CHECK_OUT and not checked_in:
                return False, "not-checked-in"
            changed = type(self).objects.filter(pk=self.pk, status=self.STATUS_ACTIVE).update(
                status=self.STATUS_USED, redeemed_at=now
            )
            if not changed:
                return False, "token-not-active"
            self.status = self.STATUS_USED
            self.redeemed_at = now
            event = AttendanceEvent.objects.create(
                employee=employee, business_unit=self.business_unit, action=self.action,
                timestamp=now, source=AttendanceEvent.SOURCE_QR_ONE_TIME,
            )
        return True, event


class LeaveRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_requests")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_leaves"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Leave Request"
        verbose_name_plural = "Leave Requests"


class AttendanceCorrectionRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="correction_requests"
    )
    event = models.ForeignKey(
        AttendanceEvent, on_delete=models.CASCADE, null=True, blank=True, related_name="corrections"
    )
    requested_timestamp = models.DateTimeField()
    requested_action = models.CharField(max_length=20, choices=AttendanceEvent.ACTION_CHOICES)
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_corrections",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Attendance Correction Request"
        verbose_name_plural = "Attendance Correction Requests"


# settings import deferred to avoid circular import at module load
from django.conf import settings  # noqa: E402
