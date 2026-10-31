"""Central reporting engine tests.

These prove that on-screen tables, totals and downloaded files all come from
the same division-scoped source data, and that payroll/transport totals are
read from their own records rather than inferred from inventory.
"""

import io
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from core.models import BusinessUnit, Department, Employee, Role, User
from inventory.models import Product, ProductBatch
from nemt.models import RideCostEstimate
from payroll.models import PayrollLine, PayrollRun, SalaryStructure
from payroll.services import calculate_payroll

from . import engine
from .exporters import export_report


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


class ReportEngineTests(TestCase):
    def setUp(self):
        self.resort = BusinessUnit.objects.create(name="Resort", code="RESORT")
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH")
        self.admin = _user("admin@test.com", "super_admin")
        self.resort_manager = _user(
            "resort-reports@test.com", "resort_inventory_manager", self.resort
        )
        self.employee_user = _user("employee@test.com", "employee", self.resort)
        self.client = APIClient()

        self.resort_product = Product.objects.create(
            sku="RES-001", name="Rice", business_unit=self.resort, unit="bag",
            min_stock=10,
        )
        self.health_product = Product.objects.create(
            sku="MED-001", name="Paracetamol", business_unit=self.health,
            unit="tablet", min_stock=10,
        )
        self.resort_batch = ProductBatch.objects.create(
            product=self.resort_product, batch_number="A-1",
            quantity_received=200, quantity_remaining=200,
            unit_cost=Decimal("10.00"),
        )
        self.health_batch = ProductBatch.objects.create(
            product=self.health_product, batch_number="B-1",
            quantity_received=300, quantity_remaining=300,
            unit_cost=Decimal("2.00"),
        )

    # -- source/total reconciliation -------------------------------------

    def test_stock_summary_rows_and_totals_match_scoped_source(self):
        report = engine.run_report(
            self.resort_manager, "inventory-stock-summary",
            {"business_unit": self.resort.pk}, paginate=False,
        )
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["rows"][0]["sku"], "RES-001")
        self.assertEqual(report["rows"][0]["usable_stock"], 200)
        self.assertEqual(report["totals"]["usable_stock"], 200)
        self.assertEqual(report["totals"]["stock_value"], 2000.0)

        source = sum(
            batch.quantity_remaining
            for batch in ProductBatch.objects.filter(business_unit=self.resort)
        )
        self.assertEqual(report["totals"]["usable_stock"], source)

    def test_aggregate_scope_only_includes_accessible_divisions(self):
        report = engine.run_report(
            self.admin, "inventory-stock-summary", {}, paginate=False
        )
        self.assertEqual(report["count"], 2)
        self.assertTrue(report["aggregate"])
        self.assertEqual(report["totals"]["usable_stock"], 500)
        self.assertEqual(report["totals"]["stock_value"], 2600.0)

    def test_cross_division_selector_is_denied(self):
        with self.assertRaises(engine.ReportPermissionDenied):
            engine.run_report(
                self.resort_manager, "inventory-stock-summary",
                {"business_unit": self.health.pk},
            )
        report = engine.run_report(
            self.resort_manager, "inventory-stock-summary", {}, paginate=False
        )
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["division"]["code"], "RESORT")

    def test_unknown_report_and_missing_permission(self):
        with self.assertRaises(engine.ReportNotFound):
            engine.run_report(self.admin, "does-not-exist", {})
        with self.assertRaises(engine.ReportPermissionDenied):
            engine.run_report(self.employee_user, "payroll-register", {})

    # -- exports reuse the exact report payload --------------------------

    def test_csv_xlsx_and_pdf_exports_match_report_payload(self):
        report = engine.run_report(
            self.admin, "inventory-stock-summary",
            {"business_unit": self.resort.pk}, paginate=False,
        )

        csv_payload, csv_type, csv_name = export_report(report, "csv")
        self.assertTrue(csv_type.startswith("text/csv"))
        self.assertTrue(csv_name.endswith(".csv"))
        text = csv_payload.decode("utf-8-sig")
        self.assertIn("RES-001", text)
        self.assertIn("TOTAL", text)
        self.assertIn("2,000.00", text)
        self.assertIn(report["title"], text)

        xlsx_payload, xlsx_type, xlsx_name = export_report(report, "xlsx")
        self.assertIn("spreadsheetml", xlsx_type)
        self.assertTrue(xlsx_name.endswith(".xlsx"))
        workbook = load_workbook(io.BytesIO(xlsx_payload))
        sheet = workbook.active
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        self.assertIn("RES-001", values)
        self.assertIn("TOTAL", values)
        self.assertIn(2000.0, values)

        pdf_payload, pdf_type, pdf_name = export_report(report, "pdf")
        self.assertEqual(pdf_type, "application/pdf")
        self.assertTrue(pdf_name.endswith(".pdf"))
        self.assertTrue(pdf_payload.startswith(b"%PDF"))

    def test_export_endpoint_uses_same_filters_and_enforces_permissions(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(
            "/api/v1/reports/export/inventory-stock-summary/",
            {"business_unit": self.resort.pk, "format": "csv"},
        )
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response["X-Report-Rows"], "1")
        self.assertIn("RES-001", response.content.decode("utf-8-sig"))
        self.assertNotIn("MED-001", response.content.decode("utf-8-sig"))

        self.client.force_authenticate(self.employee_user)
        denied = self.client.get(
            "/api/v1/reports/export/inventory-stock-summary/",
            {"business_unit": self.resort.pk, "format": "csv"},
        )
        self.assertEqual(denied.status_code, 403, denied.data)

        self.client.force_authenticate(self.resort_manager)
        cross = self.client.get(
            "/api/v1/reports/run/inventory-stock-summary/",
            {"business_unit": self.health.pk},
        )
        self.assertEqual(cross.status_code, 403, cross.data)
        own = self.client.get(
            "/api/v1/reports/run/inventory-stock-summary/",
            {"business_unit": self.resort.pk},
        )
        self.assertEqual(own.status_code, 200, own.data)
        self.assertEqual(own.data["totals"]["usable_stock"], 200)

    def test_catalog_is_filtered_by_module_permission(self):
        self.client.force_authenticate(self.resort_manager)
        response = self.client.get("/api/v1/reports/catalog/")
        self.assertEqual(response.status_code, 200)
        keys = {report["key"] for report in response.data["reports"]}
        self.assertIn("inventory-stock-summary", keys)
        self.assertNotIn("payroll-register", keys)

        self.client.force_authenticate(self.employee_user)
        response = self.client.get("/api/v1/reports/catalog/")
        keys = {report["key"] for report in response.data["reports"]}
        self.assertEqual(keys, {"management-overview"})


class PayrollAndTransportReportTests(TestCase):
    """Payroll/transport totals come from their own records, not inventory."""

    def setUp(self):
        self.resort = BusinessUnit.objects.create(name="Resort", code="RESORT")
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH")
        self.admin = _user("admin@test.com", "super_admin")
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
        self.product = Product.objects.create(
            sku="RES-900", name="Towel", business_unit=self.resort,
        )
        self.batch = ProductBatch.objects.create(
            product=self.product, batch_number="RES-900-A",
            quantity_received=40, quantity_remaining=40,
            unit_cost=Decimal("50.00"),
        )
        today = timezone.localdate()
        self.start = today - timedelta(days=30)
        self.end = today
        for offset in (2, 3):
            from attendance.models import AttendanceEvent

            AttendanceEvent.objects.create(
                employee=self.employee, business_unit=self.resort,
                action=AttendanceEvent.ACTION_CHECK_IN,
                timestamp=timezone.now() - timedelta(days=offset),
            )
        self.run, _ = calculate_payroll(
            division=self.resort, period_start=self.start, period_end=self.end,
            reference="PAY-RESORT-TEST",
        )
        self.resort_estimate = RideCostEstimate.objects.create(
            reference="RCE-RESORT", business_unit=self.resort,
            distance_km=Decimal("10.00"), duration_minutes=60,
            base_fee=Decimal("50.00"), per_km_rate=Decimal("20.00"),
            driver_hourly_rate=Decimal("100.00"), tolls=Decimal("30.00"),
        )
        self.health_estimate = RideCostEstimate.objects.create(
            reference="RCE-HEALTH", business_unit=self.health,
            distance_km=Decimal("5.00"), duration_minutes=30,
            base_fee=Decimal("40.00"), per_km_rate=Decimal("20.00"),
            driver_hourly_rate=Decimal("80.00"), tolls=Decimal("0.00"),
        )

    def test_payroll_report_matches_payroll_lines(self):
        report = engine.run_report(
            self.admin, "payroll-register",
            {"business_unit": self.resort.pk}, paginate=False,
        )
        self.assertEqual(report["count"], 1)
        line = PayrollLine.objects.get(run=self.run)
        self.assertEqual(report["rows"][0]["employee_id"], "EMP-001")
        self.assertEqual(report["totals"]["net"], float(line.net))
        self.assertEqual(report["totals"]["gross"], float(line.gross))
        self.assertEqual(report["totals"]["days_present"], line.days_present)
        self.assertEqual(line.net, Decimal("10600.00"))
        self.assertEqual(line.days_present, 2)

    def test_payroll_summary_is_division_scoped(self):
        resort_report = engine.run_report(
            self.admin, "accounting-payroll-summary",
            {"business_unit": self.resort.pk}, paginate=False,
        )
        self.assertEqual(resort_report["count"], 1)
        self.assertEqual(resort_report["totals"]["net"], 10600.0)

        health_report = engine.run_report(
            self.admin, "accounting-payroll-summary",
            {"business_unit": self.health.pk}, paginate=False,
        )
        self.assertEqual(health_report["count"], 0)
        self.assertEqual(health_report["totals"], {})

    def test_transport_totals_use_cost_estimates_only(self):
        report = engine.run_report(
            self.admin, "transport-cost-estimates",
            {"business_unit": self.resort.pk}, paginate=False,
        )
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["rows"][0]["reference"], "RCE-RESORT")
        self.assertEqual(report["totals"]["total_cost"], 380.0)
        self.assertEqual(
            report["totals"]["total_cost"],
            float(self.resort_estimate.total_cost),
        )

        aggregate = engine.run_report(
            self.admin, "transport-cost-estimates", {}, paginate=False
        )
        self.assertEqual(aggregate["count"], 2)
        self.assertEqual(
            aggregate["totals"]["total_cost"],
            float(self.resort_estimate.total_cost + self.health_estimate.total_cost),
        )

    def test_management_overview_combines_real_sources(self):
        report = engine.run_report(
            self.admin, "management-overview",
            {"business_unit": self.resort.pk}, paginate=False,
        )
        self.assertEqual(report["count"], 1)
        row = report["rows"][0]
        self.assertEqual(row["division"], "Resort")
        self.assertEqual(row["employees"], 1)
        self.assertEqual(row["products"], 1)
        self.assertEqual(row["usable_stock"], 40)
        self.assertEqual(row["stock_value"], 2000.0)
        self.assertEqual(row["payroll_net"], 10600.0)
