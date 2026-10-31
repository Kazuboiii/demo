"""Payroll calculation service.

Payroll is derived only from configured salary structures and attendance day
counts. Inventory, procurement and transport data are never read here.
"""

from decimal import Decimal

from django.db import transaction

from attendance.models import AttendanceEvent

from .models import PayrollLine, PayrollRun, SalaryStructure


class PayrollError(Exception):
    """Raised when a payroll run cannot be calculated."""


def _attendance_days(employee, start, end):
    return (
        AttendanceEvent.objects.filter(
            employee=employee,
            action=AttendanceEvent.ACTION_CHECK_IN,
            timestamp__date__range=(start, end),
        )
        .dates("timestamp", "day")
        .count()
    )


@transaction.atomic
def calculate_payroll(*, division, period_start, period_end, created_by=None,
                      reference=""):
    """Create a payroll run for one division and period.

    Returns ``(run, created)``. Re-running the same reference returns the
    existing run instead of duplicating lines.
    """
    if period_start > period_end:
        raise PayrollError("The payroll period start must be before its end.")
    reference = (reference or "").strip() or (
        f"PAY-{division.code}-{period_start:%Y%m%d}-{period_end:%Y%m%d}"
    )
    existing = PayrollRun.objects.filter(reference=reference).first()
    if existing is not None:
        if existing.business_unit_id != division.pk:
            raise PayrollError("This payroll reference belongs to another division.")
        return existing, False

    structures = (
        SalaryStructure.objects.filter(
            business_unit=division, is_active=True, employee__is_active=True
        )
        .select_related("employee")
        .order_by("employee__employee_id")
    )
    if not structures.exists():
        raise PayrollError(
            "No active salary structures exist for this division. "
            "Configure salary structures before running payroll."
        )

    run = PayrollRun.objects.create(
        reference=reference,
        business_unit=division,
        period_start=period_start,
        period_end=period_end,
        created_by=created_by,
    )
    for structure in structures:
        days = _attendance_days(structure.employee, period_start, period_end)
        gross = structure.gross
        deductions = structure.deductions_for(gross)
        net = gross - deductions
        PayrollLine.objects.create(
            run=run,
            employee=structure.employee,
            basic_salary=structure.basic_salary,
            allowances=structure.allowances,
            deductions=deductions,
            gross=gross,
            net=net,
            days_present=days,
            notes="Calculated from salary structure and attendance days.",
        )
    return run, True
