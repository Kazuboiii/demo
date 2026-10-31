"""Payroll source records.

Payroll is calculated only from configured salary structures and attendance
day counts. It never reads inventory, procurement or transport data.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import BusinessUnit, Employee


class SalaryStructure(models.Model):
    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="salary_structure"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="salary_structures"
    )
    currency = models.CharField(max_length=8, default="NPR")
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    housing_allowance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_rate_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    effective_from = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__employee_id"]
        verbose_name = "Salary Structure"
        verbose_name_plural = "Salary Structures"

    def __str__(self):
        return f"{self.employee.employee_id} - {self.basic_salary} {self.currency}"

    @property
    def allowances(self):
        return self.housing_allowance + self.transport_allowance + self.other_allowance

    @property
    def gross(self):
        return self.basic_salary + self.allowances

    def deductions_for(self, gross=None):
        gross = self.gross if gross is None else gross
        tax = (gross * self.tax_rate_percent / Decimal("100")).quantize(Decimal("0.01"))
        return tax + self.other_deduction


class PayrollRun(models.Model):
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
        BusinessUnit, on_delete=models.PROTECT, related_name="payroll_runs"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    currency = models.CharField(max_length=8, default="NPR")
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payroll_runs",
    )
    approved_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_payroll_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]
        verbose_name = "Payroll Run"
        verbose_name_plural = "Payroll Runs"

    def __str__(self):
        return f"{self.reference} ({self.period_start}..{self.period_end})"

    @property
    def total_gross(self):
        return sum((line.gross for line in self.lines.all()), Decimal("0"))

    @property
    def total_net(self):
        return sum((line.net for line in self.lines.all()), Decimal("0"))


class PayrollLine(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="payroll_lines"
    )
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    allowances = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    days_present = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=250, blank=True, default="")

    class Meta:
        unique_together = [("run", "employee")]
        ordering = ["employee__employee_id"]
        verbose_name = "Payroll Line"
        verbose_name_plural = "Payroll Lines"

    def __str__(self):
        return f"{self.employee.employee_id} net {self.net}"
