"""Repeatable fictional demo records with reconciled inventory and attendance."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.core.management.base import BaseCommand
from django.db import transaction
from core.role_access import ROLE_CHOICES, shared_role_user
from core.models import BusinessUnit
from attendance.models import AttendanceEvent, Shift
from inventory.models import Location, Supplier, Product
from inventory.services import post_receipt
from payroll.models import SalaryStructure, ExpenseCategory, Expense, RevenueRecord


class Command(BaseCommand):
    help = "Add fictional sample data without replacing existing records or duplicating stock."

    @transaction.atomic
    def handle(self, *args, **options):
        users = {code: shared_role_user(code) for code, _, _ in ROLE_CHOICES}
        for index, (code, user) in enumerate(users.items()):
            employee = user.employee_record
            unit = employee.business_unit
            shift, _ = Shift.objects.get_or_create(business_unit=unit, name="Sample day shift",
                defaults={"start_time": time(9), "end_time": time(17), "grace_minutes": 10})
            SalaryStructure.objects.get_or_create(employee=employee, defaults={
                "business_unit": unit, "basic_salary": Decimal(30000 + index * 5000),
                "transport_allowance": Decimal("2000"), "currency": "NPR",
                "effective_from": date(2026, 10, 1)})
            # Five completed historical shifts. Never synthesize today's live check-in.
            for offset in range(5):
                day = date(2026, 10, 19) + timedelta(days=offset)
                for action, hour in (("check_in", 9), ("check_out", 17)):
                    AttendanceEvent.objects.get_or_create(employee=employee, action=action,
                        timestamp=datetime.combine(day, time(hour), tzinfo=ZoneInfo("Asia/Kathmandu")),
                        defaults={"business_unit": unit, "shift": shift, "source": "manual",
                                  "notes": "SAMPLE: fictional completed eight-hour shift"})
        products = {
            "RESORT": [("TOWEL", "Sample bath towel - cotton", "piece", 120, "650", 30),
                       ("WATER", "Sample bottled water 1 litre", "bottle", 240, "25", 60),
                       ("SOAP", "Sample guest soap 30 g", "piece", 300, "18", 80)],
            "HEALTH": [("GLOVES", "Sample nitrile gloves - box of 100", "box", 40, "850", 10),
                       ("MASK", "Sample surgical mask - box of 50", "box", 60, "350", 15),
                       ("GAUZE", "Sample sterile gauze - pack of 10", "pack", 100, "120", 25)],
        }
        for code, rows in products.items():
            unit = BusinessUnit.objects.get(code=code)
            location, _ = Location.objects.get_or_create(business_unit=unit, name="Sample central store")
            supplier, _ = Supplier.objects.get_or_create(business_unit=unit, code=f"SAMPLE-{code}",
                defaults={"name": f"Sample {code.title()} Supplies", "email": f"{code.lower()}@example.invalid"})
            lines = []
            for sku, name, measure, quantity, cost, minimum in rows:
                product, _ = Product.objects.get_or_create(business_unit=unit, sku=f"SAMPLE-{sku}",
                    defaults={"name": name, "unit": measure, "category": "Sample supplies", "min_stock": minimum,
                              "batch_tracking_required": True, "is_perishable": code == "HEALTH"})
                lines.append({"product": product, "quantity": quantity, "unit_cost": Decimal(cost),
                              "batch_number": f"SAMPLE-{sku}-001",
                              "expiry_date": date(2028, 10, 31) if code == "HEALTH" else None})
            post_receipt(division=unit, location=location, supplier=supplier,
                reference=f"SAMPLE-RECEIPT-{code}-001", lines=lines,
                received_by=users["super_admin"], notes="Fictional opening stock; costs in NPR")
            category, _ = ExpenseCategory.objects.get_or_create(business_unit=unit, code="SAMPLE-OPS",
                defaults={"name": "Sample operating costs"})
            Expense.objects.get_or_create(reference=f"SAMPLE-EXP-{code}-001", defaults={
                "business_unit": unit, "category": category, "amount": Decimal("4500"),
                "description": "Sample monthly cleaning service", "currency": "NPR", "status": "draft"})
            revenue_category, _ = ExpenseCategory.objects.get_or_create(business_unit=unit, code="SAMPLE-SERVICE",
                defaults={"name": "Sample service revenue"})
            RevenueRecord.objects.get_or_create(reference=f"SAMPLE-REV-{code}-001", defaults={
                "business_unit": unit, "category": revenue_category, "amount": Decimal("28000"), "currency": "NPR",
                "description": "Fictional sample service revenue", "recorded_by": users["accountant"]})
        self.stdout.write(self.style.SUCCESS("Sample workspace ready: 6 employees, 60 attendance events, 6 stocked products, salaries and finance records."))
