"""
Core domain models shared across the whole platform:

- BusinessUnit: healthcare / resort (and any future unit)
- Role: platform role with business-unit scoping
- Department: belongs to a business unit
- User: platform account (email based)
- Employee: HR record linked to a user, assigned to a unit + department
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q


class BusinessUnit(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)  # e.g. "HEALTH", "RESORT"
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Business Unit"
        verbose_name_plural = "Business Units"

    def __str__(self):
        return self.name


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)  # e.g. "Super Administrator"
    code = models.CharField(max_length=40, unique=True)  # e.g. "super_admin"
    business_unit = models.ForeignKey(
        BusinessUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Null means the role is global (e.g. Super Administrator).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_global(self):
        return self.business_unit is None


class Department(models.Model):
    name = models.CharField(max_length=100)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="departments"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["business_unit__name", "name"]
        unique_together = [("name", "business_unit")]
        verbose_name = "Department"
        verbose_name_plural = "Departments"

    def __str__(self):
        return f"{self.business_unit.name} - {self.name}"


class DivisionAccess(models.Model):
    """Explicit grant of a user to a business division.

    The primary business unit on ``User`` remains the default scope. Additional
    grants are required for cross-division roles (HR, accountant) that must be
    able to switch between Resort and Healthcare inventory without receiving
    write access to stock.
    """

    LEVEL_READ = "read"
    LEVEL_WRITE = "write"
    LEVEL_ADMIN = "admin"
    LEVEL_CHOICES = [
        (LEVEL_READ, "Read"),
        (LEVEL_WRITE, "Write"),
        (LEVEL_ADMIN, "Admin"),
    ]

    user = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="division_access"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="user_grants"
    )
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_READ)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "business_unit")]
        ordering = ["user__email", "business_unit__name"]
        verbose_name = "Division Access"
        verbose_name_plural = "Division Access Grants"

    def __str__(self):
        return f"{self.user.email} -> {self.business_unit.code} ({self.level})"


class RoleAssignment(models.Model):
    """Optional multi-role assignment. ``User.role`` remains the primary role."""

    user = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")
    business_unit = models.ForeignKey(
        BusinessUnit,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "role", "business_unit")]
        ordering = ["user__email", "role__name"]
        verbose_name = "Role Assignment"
        verbose_name_plural = "Role Assignments"

    def __str__(self):
        unit = self.business_unit.code if self.business_unit else "global"
        return f"{self.user.email}: {self.role.code} @ {unit}"


class User(AbstractUser):
    """Platform account. Email is the unique login identifier."""

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True, default="")
    business_unit = models.ForeignKey(
        BusinessUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
        help_text="Primary business unit of the user. Super admins may have none.",
    )
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name="users", null=True, blank=True
    )
    is_approved = models.BooleanField(default=True)
    is_demo = models.BooleanField(
        default=False,
        help_text=(
            "True for seeded demo accounts. This is the only way an account can "
            "use the gated /auth/demo-login/ endpoint; regular accounts are never "
            "flagged and their passwords are never affected by seeding."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        ordering = ["email"]
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.email

    @property
    def role_code(self):
        return self.role.code if self.role else None

    @property
    def business_unit_code(self):
        return self.business_unit.code if self.business_unit else None

    def has_role(self, *codes):
        return self.role_code in codes if self.role_code else False

    @property
    def is_global_scope(self):
        """Roles allowed to look across divisions (still subject to module perms)."""
        return bool(
            self.is_superuser
            or self.has_role("super_admin", "hr_manager", "accountant")
        )

    def accessible_business_units(self):
        """Business divisions this account may see.

        Global-scope roles see every active division. Everyone else sees their
        primary unit plus any explicit ``DivisionAccess`` grants.
        """
        if self.is_global_scope:
            return BusinessUnit.objects.filter(is_active=True)
        if not self.is_authenticated:
            return BusinessUnit.objects.none()
        ids = set()
        if self.business_unit_id:
            ids.add(self.business_unit_id)
        ids.update(
            self.division_access.filter(is_active=True).values_list(
                "business_unit_id", flat=True
            )
        )
        return BusinessUnit.objects.filter(pk__in=ids, is_active=True)

    def can_access_business_unit(self, bu):
        """Business-division scoping rule (single source of truth)."""
        if bu is None:
            return False
        if self.is_global_scope:
            return True
        if not self.is_authenticated:
            return False
        if self.business_unit_id == bu.pk:
            return True
        return self.division_access.filter(
            business_unit=bu, is_active=True
        ).exists()


class Employee(models.Model):
    """HR employee record. One per user with employee role."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employee_record")
    employee_id = models.CharField(max_length=30, unique=True)  # e.g. "EMP-0001"
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="employees"
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="employees"
    )
    designation = models.CharField(max_length=100, blank=True, default="")
    hire_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["employee_id"]
        verbose_name = "Employee"
        verbose_name_plural = "Employees"

    def __str__(self):
        return f"{self.employee_id} - {self.user.get_full_name() or self.user.email}"


# ---------------------------------------------------------------------------
# Enterprise division registry
# ---------------------------------------------------------------------------

DIVISION_RESORT_AND_HOSPITALITY = "resort_and_hospitality"
DIVISION_HEALTHCARE_AND_PHARMACY = "healthcare_and_pharmacy"
DIVISION_HUMAN_RESOURCES = "human_resources"
DIVISION_FINANCE_AND_ACCOUNTING = "finance_and_accounting"
DIVISION_TRANSPORTATION_AND_RIDE_MANAGEMENT = "transportation_and_ride_management"
DIVISION_ATTENDANCE_AND_WORKFORCE_MANAGEMENT = "attendance_and_workforce_management"
DIVISION_ENTERPRISE_ADMINISTRATION = "enterprise_administration"

ENTERPRISE_DIVISION_NAMES = {
    "RESORT": "Resort and Hospitality",
    "HEALTH": "Healthcare and Pharmacy",
    "HR": "Human Resources",
    "FINANCE": "Finance and Accounting",
    "TRANSPORT": "Transportation and Ride Management",
    "ATTENDANCE": "Attendance and Workforce Management",
    "ADMIN": "Enterprise Administration",
}

DIVISION_BY_BUSINESS_UNIT_CODE = {
    "RESORT": DIVISION_RESORT_AND_HOSPITALITY,
    "HEALTH": DIVISION_HEALTHCARE_AND_PHARMACY,
    "HR": DIVISION_HUMAN_RESOURCES,
    "FINANCE": DIVISION_FINANCE_AND_ACCOUNTING,
    "TRANSPORT": DIVISION_TRANSPORTATION_AND_RIDE_MANAGEMENT,
    "ATTENDANCE": DIVISION_ATTENDANCE_AND_WORKFORCE_MANAGEMENT,
    "ADMIN": DIVISION_ENTERPRISE_ADMINISTRATION,
}

DIVISION_CORE_BUSINESS_UNITS = frozenset({
    DIVISION_RESORT_AND_HOSPITALITY,
    DIVISION_HEALTHCARE_AND_PHARMACY,
    DIVISION_HUMAN_RESOURCES,
    DIVISION_FINANCE_AND_ACCOUNTING,
    DIVISION_TRANSPORTATION_AND_RIDE_MANAGEMENT,
    DIVISION_ATTENDANCE_AND_WORKFORCE_MANAGEMENT,
    DIVISION_ENTERPRISE_ADMINISTRATION,
})


class EnterpriseDivision(models.Model):
    """
    Logical enterprise division used by the task's division list.

    Each record maps to one concrete operational ``BusinessUnit`` that holds the
    shared operational data (employees, inventory, fleet, attendance, rides).
    New divisions from the task brief are represented here; the underlying
    employee/inventory/fleet/attendance data still lives in the shared
    operational business units for now.
    """

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, unique=True)
    business_unit = models.OneToOneField(
        BusinessUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="enterprise_division",
        help_text="Operational business unit backing this enterprise division, if any.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Enterprise Division"
        verbose_name_plural = "Enterprise Divisions"

    def __str__(self):
        return self.name

    @classmethod
    def ensure_registered(cls):
        """Idempotent registration of the brief's required divisions."""
        for code, name in [
            (DIVISION_RESORT_AND_HOSPITALITY, "Resort and Hospitality"),
            (DIVISION_HEALTHCARE_AND_PHARMACY, "Healthcare and Pharmacy"),
            (DIVISION_HUMAN_RESOURCES, "Human Resources"),
            (DIVISION_FINANCE_AND_ACCOUNTING, "Finance and Accounting"),
            (DIVISION_TRANSPORTATION_AND_RIDE_MANAGEMENT, "Transportation and Ride Management"),
            (DIVISION_ATTENDANCE_AND_WORKFORCE_MANAGEMENT, "Attendance and Workforce Management"),
            (DIVISION_ENTERPRISE_ADMINISTRATION, "Enterprise Administration"),
        ]:
            cls.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "business_unit_id": getattr(cls, "_business_unit_for_code", {}).get(code),
                    "is_active": True,
                },
            )
