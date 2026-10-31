"""Payroll calculation tests.

Payroll must be derived only from salary structures and attendance days. It
must never write inventory records or derive amounts from stock.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from attendance.models import AttendanceEvent
from core.models import BusinessUnit, Department, Employee, Role, User
from inventory.models import Product, ProductBatch, StockMovement

from . import services
from .models import PayrollLine, PayrollRun, SalaryStructure


def _role(code):
    role, _ = Role.objects.get_or_create(
        code=code, defaults={"name": code.replace("_", " ").title()}
    )
    return role


def _user(email, role_code, unit=None):
    return User.objects.create_user(
        username=email,
        email=email,
        password="pass123",
        role=_role(role_code),
        business_unit=unit,
        is_active=True,
        is_approved=True,
    )


class PayrollCalculationTests(TestCase):
    def setUp(self):
        self.resort = BusinessUnit.objects.create(name="Resort", code="RESORT")
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH")
        self.department = Department.objects.create(
            name="Front Office", business_unit=self.resort
        )
        self.employee_user = _user("staff@test.com", "employee", self.resort)
        self.employee = Employee.objects.create(
            user=self.employee_user, business_unit=self.resort,
            department=self.department, employee_id="EMP-001",
        )
        self.structure = SalaryStructure.objects.create(
            employee=self.employee, business_unit=self.resort,
            basic_salary=Decimal("10000.00"),
            housing_allowance=Decimal("1000.00"),
            transport_allowance=Decimal("500.00"),
            other_allowance=Decimal("500.00"),
            tax_rate_percent=Decimal("10.00"),
            other_deduction=Decimal("200.00"),
        )
        today = timezone.localdate()
        self.start = today - timedelta(days=30)
        self.end = today
        for offset in (2, 3):
            AttendanceEvent.objects.create(
                employee=self.employee, business_unit=self.resort,
                action=AttendanceEvent.ACTION_CHECK_IN,
                timestamp=timezone.now() - timedelta(days=offset),
            )

    def test_calculation_uses_salary_structure_and_attendance_days(self):
        run, created = services.calculate_payroll(
            division=self.resort, period_start=self.start, period_end=self.end,
            reference="PAY-TEST-1",
        )
        self.assertTrue(created)
        self.assertEqual(run.lines.count(), 1)
        line = run.lines.get()
        self.assertEqual(line.employee, self.employee)
        self.assertEqual(line.basic_salary, Decimal("10000.00"))
        self.assertEqual(line.allowances, Decimal("2000.00"))
        self.assertEqual(line.gross, Decimal("12000.00"))
        self.assertEqual(line.deductions, Decimal("1400.00"))
        self.assertEqual(line.net, Decimal("10600.00"))
        self.assertEqual(line.days_present, 2)
        self.assertEqual(run.total_gross, Decimal("12000.00"))
        self.assertEqual(run.total_net, Decimal("10600.00"))

    def test_replaying_the_same_reference_is_idempotent(self):
        run, created = services.calculate_payroll(
            division=self.resort, period_start=self.start, period_end=self.end,
            reference="PAY-TEST-2",
        )
        replay, created_again = services.calculate_payroll(
            division=self.resort, period_start=self.start, period_end=self.end,
            reference="PAY-TEST-2",
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(run.pk, replay.pk)
        self.assertEqual(PayrollRun.objects.count(), 1)
        self.assertEqual(PayrollLine.objects.count(), 1)

    def test_default_reference_is_deterministic(self):
        first, created = services.calculate_payroll(
            division=self.resort, period_start=self.start, period_end=self.end,
        )
        second, created_again = services.calculate_payroll(
            division=self.resort, period_start=self.start, period_end=self.end,
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            first.reference,
            f"PAY-RESORT-{self.start:%Y%m%d}-{self.end:%Y%m%d}",
        )

    def test_missing_salary_structure_is_rejected(self):
        SalaryStructure.objects.all().delete()
        with self.assertRaises(services.PayrollError):
            services.calculate_payroll(
                division=self.resort, period_start=self.start,
                period_end=self.end, reference="PAY-EMPTY",
            )
        self.assertFalse(PayrollRun.objects.exists())

    def test_invalid_period_is_rejected(self):
        with self.assertRaises(services.PayrollError):
            services.calculate_payroll(
                division=self.resort, period_start=self.end,
                period_end=self.start, reference="PAY-BAD-DATES",
            )

    def test_payroll_never_writes_inventory(self):
        product = Product.objects.create(
            sku="RES-001", name="Rice", business_unit=self.resort,
        )
        batch = ProductBatch.objects.create(
            product=product, batch_number="A-1", quantity_received=100,
            quantity_remaining=100, unit_cost=Decimal("10.00"),
        )
        movements_before = StockMovement.objects.count()
        services.calculate_payroll(
            division=self.resort, period_start=self.start, period_end=self.end,
            reference="PAY-NO-STOCK",
        )
        batch.refresh_from_db()
        self.assertEqual(batch.quantity_remaining, 100)
        self.assertEqual(StockMovement.objects.count(), movements_before)


class PayrollApiTests(TestCase):
    def setUp(self):
        self.resort = BusinessUnit.objects.create(name="Resort", code="RESORT")
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH")
        self.hr = _user("hr@test.com", "hr_manager")
        self.accountant = _user("accountant@test.com", "accountant")
        self.employee_user = _user("staff@test.com", "employee", self.resort)
        self.employee = Employee.objects.create(
            user=self.employee_user, business_unit=self.resort,
            employee_id="EMP-001",
        )
        SalaryStructure.objects.create(
            employee=self.employee, business_unit=self.resort,
            basic_salary=Decimal("5000.00"), tax_rate_percent=Decimal("5.00"),
        )
        today = timezone.localdate()
        self.start = (today - timedelta(days=30)).isoformat()
        self.end = today.isoformat()
        self.client = APIClient()

    def _payload(self, reference="PAY-API-1"):
        return {
            "business_unit": self.resort.pk,
            "period_start": self.start,
            "period_end": self.end,
            "reference": reference,
        }

    def test_hr_can_calculate_and_replay_returns_200(self):
        self.client.force_authenticate(self.hr)
        first = self.client.post(
            "/api/v1/payroll/runs/calculate/", self._payload(), format="json"
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["total_net"], 4750.0)
        replay = self.client.post(
            "/api/v1/payroll/runs/calculate/", self._payload(), format="json"
        )
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay.data["id"], first.data["id"])
        self.assertEqual(PayrollRun.objects.count(), 1)

    def test_accountant_and_employee_cannot_run_payroll(self):
        for user in (self.accountant, self.employee_user):
            self.client.force_authenticate(user)
            response = self.client.post(
                "/api/v1/payroll/runs/calculate/", self._payload(), format="json"
            )
            self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(PayrollRun.objects.exists())

    def test_hr_can_approve_then_mark_paid(self):
        self.client.force_authenticate(self.hr)
        created = self.client.post(
            "/api/v1/payroll/runs/calculate/", self._payload(), format="json"
        )
        run_id = created.data["id"]
        approved = self.client.post(f"/api/v1/payroll/runs/{run_id}/approve/")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")
        paid = self.client.post(f"/api/v1/payroll/runs/{run_id}/mark_paid/")
        self.assertEqual(paid.status_code, 200, paid.data)
        self.assertEqual(paid.data["status"], "paid")

    def test_salary_structure_division_is_enforced(self):
        self.client.force_authenticate(self.hr)
        response = self.client.post("/api/v1/payroll/salary-structures/", {
            "employee": self.employee.pk,
            "business_unit": self.health.pk,
            "basic_salary": "1000.00",
        }, format="json")
        self.assertEqual(response.status_code, 400, response.data)
