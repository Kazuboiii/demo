"""
Deterministic seed script for the Unified Enterprise Management System.

Creates fictional sample data for healthcare and resort business units.
Safe to re-run: clears sample data and re-creates it.

Development-only credentials (every account password: "admin123"):

  super@buildakar.com        Super Administrator (both units)
  hcadmin@buildakar.com      Healthcare Administrator
  rsadmin@buildakar.com      Resort Administrator
  hr@buildakar.com           HR Manager
  fleet@buildakar.com        Fleet Manager
  inv@buildakar.com          Inventory Manager
  driver@buildakar.com       Driver
  emp@buildakar.com          Regular Employee
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import BusinessUnit, Department, Employee, Role, User

User = get_user_model()

PASSWORD = "admin123"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now():
    return timezone.now()


def _create_user(email, first, last, role, bu=None, staff=False):
    user, _ = User.objects.update_or_create(
        email=email,
        defaults={
            "username": email,
            "first_name": first,
            "last_name": last,
            "role": role,
            "business_unit": bu,
            "is_active": True,
            "is_approved": True,
            "is_staff": staff,
            "is_superuser": role.code == "super_admin",
        },
    )
    user.set_password(PASSWORD)
    user.save()
    return user


def _get_or_create_role(code, name, bu=None):
    role, _ = Role.objects.update_or_create(
        code=code,
        defaults={"name": name, "business_unit": bu, "is_active": True},
    )
    return role


def _employee(user, employee_id, bu, dept=None, designation="Staff"):
    emp, _ = Employee.objects.update_or_create(
        user=user,
        defaults={
            "employee_id": employee_id,
            "business_unit": bu,
            "department": dept,
            "designation": designation,
            "hire_date": _now().date() - timedelta(days=365),
            "is_active": True,
        },
    )
    return emp


class Command(BaseCommand):
    help = "Seed deterministic sample data for the UEMS prototype."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding sample data...")

        # ---- Business units ------------------------------------------------
        health, _ = BusinessUnit.objects.update_or_create(
            code="HEALTH",
            defaults={"name": "Healthcare Operations", "is_active": True},
        )
        resort, _ = BusinessUnit.objects.update_or_create(
            code="RESORT",
            defaults={"name": "Resort Operations", "is_active": True},
        )

        # ---- Roles ---------------------------------------------------------
        role_super = _get_or_create_role("super_admin", "Super Administrator")
        role_hc_admin = _get_or_create_role("healthcare_admin", "Healthcare Administrator", health)
        role_rs_admin = _get_or_create_role("resort_admin", "Resort Administrator", resort)
        # One global HR role; HR may switch divisions but stays read-only on stock.
        role_hr = _get_or_create_role("hr_manager", "HR Manager", None)
        role_fleet = _get_or_create_role("fleet_manager", "Fleet Manager", health)
        role_inv_hc = _get_or_create_role(
            "healthcare_inventory_manager", "Healthcare Inventory Manager", health
        )
        role_inv_rs = _get_or_create_role(
            "resort_inventory_manager", "Resort Inventory Manager", resort
        )
        # Legacy role retained so older accounts keep working.
        role_inv_legacy = _get_or_create_role(
            "inventory_manager", "Inventory Manager (legacy)", None
        )
        role_accountant = _get_or_create_role("accountant", "Accountant", None)
        role_driver = _get_or_create_role("driver", "Driver", health)
        role_emp = _get_or_create_role("employee", "Employee", resort)

        # ---- Users ---------------------------------------------------------
        u_super = _create_user("super@buildakar.com", "Buildakar", "Admin", role_super, staff=True)
        u_hc = _create_user("hcadmin@buildakar.com", "Ramesh", "Health", role_hc_admin, health, staff=True)
        u_rs = _create_user("rsadmin@buildakar.com", "Sita", "Resort", role_rs_admin, resort, staff=True)
        u_hr = _create_user("hr@buildakar.com", "Kiran", "HR", role_hr, None, staff=True)
        u_fleet = _create_user("fleet@buildakar.com", "Arun", "Fleet", role_fleet, health, staff=True)
        u_inv = _create_user("inv@buildakar.com", "Meena", "Inventory", role_inv_hc, health, staff=True)
        u_inv_rs = _create_user("invrs@buildakar.com", "Resort", "Inventory", role_inv_rs, resort, staff=True)
        u_accountant = _create_user(
            "accountant@buildakar.com", "Bina", "Accountant", role_accountant, None, staff=True
        )
        u_driver = _create_user("driver@buildakar.com", "Prakash", "Driver", role_driver, health)
        u_emp = _create_user("emp@buildakar.com", "Nisha", "Employee", role_emp, resort)

        # ---- Departments ---------------------------------------------------
        dept_nursing, _ = Department.objects.update_or_create(
            name="Nursing", business_unit=health,
            defaults={"is_active": True},
        )
        dept_pharmacy, _ = Department.objects.update_or_create(
            name="Pharmacy", business_unit=health,
            defaults={"is_active": True},
        )
        dept_emergency, _ = Department.objects.update_or_create(
            name="Emergency", business_unit=health,
            defaults={"is_active": True},
        )
        dept_hc_admin, _ = Department.objects.update_or_create(
            name="Administration", business_unit=health,
            defaults={"is_active": True},
        )
        dept_front, _ = Department.objects.update_or_create(
            name="Front Office", business_unit=resort,
            defaults={"is_active": True},
        )
        dept_housekeeping, _ = Department.objects.update_or_create(
            name="Housekeeping", business_unit=resort,
            defaults={"is_active": True},
        )
        dept_kitchen, _ = Department.objects.update_or_create(
            name="Kitchen", business_unit=resort,
            defaults={"is_active": True},
        )
        dept_maint, _ = Department.objects.update_or_create(
            name="Maintenance", business_unit=resort,
            defaults={"is_active": True},
        )

        # ---- Employees -----------------------------------------------------
        _employee(u_super, "EMP-0000", health, dept_hc_admin, "System Administrator")
        _employee(u_hc, "EMP-1001", health, dept_hc_admin, "Healthcare Administrator")
        _employee(u_rs, "EMP-2001", resort, dept_front, "Resort Administrator")
        _employee(u_hr, "EMP-1002", health, dept_hc_admin, "HR Manager")
        _employee(u_fleet, "EMP-1003", health, dept_hc_admin, "Fleet Manager")
        _employee(u_inv, "EMP-1004", health, dept_pharmacy, "Inventory Manager")
        _employee(u_inv_rs, "EMP-2005", resort, dept_front, "Inventory Manager")
        _employee(u_accountant, "EMP-1008", health, dept_hc_admin, "Accountant")
        _employee(u_driver, "EMP-1005", health, dept_emergency, "Driver")
        _employee(u_emp, "EMP-2002", resort, dept_housekeeping, "Housekeeping Associate")

        # extra staff for shared QR
        extra = [
            ("EMP-1006", "Anita", "Sharma", role_hc_admin, health, dept_nursing, "Nurse"),
            ("EMP-1007", "Rajiv", "Patel", role_hc_admin, health, dept_emergency, "Paramedic"),
            ("EMP-2003", "Lama", "Tsering", role_emp, resort, dept_kitchen, "Kitchen Steward"),
            ("EMP-2004", "Karma", "Dawa", role_emp, resort, dept_front, "Front Desk Agent"),
        ]
        extra_users = []
        for eid, fn, ln, role, bu, dept, desig in extra:
            email = f"{fn.lower()}.{ln.lower()}@buildakar.com"
            u = _create_user(email, fn, ln, role, bu)
            _employee(u, eid, bu, dept, desig)
            extra_users.append(u)

        self.stdout.write("Core data seeded.")

        # ---- Attendance (imported inside to keep command self-contained) --
        from attendance.models import AttendanceEvent, Shift

        # Shifts
        shift_day, _ = Shift.objects.update_or_create(
            name="Day Shift", business_unit=health,
            defaults={"start_time": time(6, 0), "end_time": time(14, 0),
                      "overnight": False, "grace_minutes": 15, "is_active": True},
        )
        shift_night, _ = Shift.objects.update_or_create(
            name="Night Shift", business_unit=health,
            defaults={"start_time": time(22, 0), "end_time": time(6, 0),
                      "overnight": True, "grace_minutes": 15, "is_active": True},
        )
        shift_resort_day, _ = Shift.objects.update_or_create(
            name="Day Shift", business_unit=resort,
            defaults={"start_time": time(8, 0), "end_time": time(16, 0),
                      "overnight": False, "grace_minutes": 15, "is_active": True},
        )

        now = _now()
        today = now.date()

        def _attendance(employee, action, shift, minutes_offset, source, unit):
            ts = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                minutes=minutes_offset
            )
            return AttendanceEvent.objects.create(
                employee=employee,
                business_unit=unit,
                shift=shift,
                action=action,
                timestamp=ts,
                source=source,
                notes="Seeded attendance record",
            )

        # Recent attendance history
        emp_driver = Employee.objects.get(employee_id="EMP-1005")
        emp_nurse = Employee.objects.get(employee_id="EMP-1006")
        emp_emp = Employee.objects.get(employee_id="EMP-2002")
        emp_chef = Employee.objects.get(employee_id="EMP-2003")

        _attendance(emp_driver, "check_in", shift_day, 480, AttendanceEvent.SOURCE_MANUAL, health)
        _attendance(emp_driver, "check_out", shift_day, 900, AttendanceEvent.SOURCE_MANUAL, health)
        _attendance(emp_nurse, "check_in", shift_night, 1320, AttendanceEvent.SOURCE_MANUAL, health)
        _attendance(emp_nurse, "check_out", shift_night, 1740, AttendanceEvent.SOURCE_MANUAL, health)
        _attendance(emp_emp, "check_in", shift_resort_day, 480, AttendanceEvent.SOURCE_MANUAL, resort)
        _attendance(emp_emp, "check_out", shift_resort_day, 900, AttendanceEvent.SOURCE_MANUAL, resort)
        _attendance(emp_chef, "check_in", shift_resort_day, 450, AttendanceEvent.SOURCE_MANUAL, resort)

        self.stdout.write("Attendance seeded.")

        # ---- Fleet ---------------------------------------------------------
        from fleet.models import DriverProfile, GPSPosition, TrackingDevice, Vehicle, VehicleAssignment

        v1, _ = Vehicle.objects.update_or_create(
            license_plate="BA-1001",
            defaults={
                "business_unit": health,
                "make": "Toyota",
                "model": "Hiace Ambulance",
                "year": 2022,
                "capacity": 3,
                "status": "available",
            },
        )
        v2, _ = Vehicle.objects.update_or_create(
            license_plate="BA-1002",
            defaults={
                "business_unit": health,
                "make": "Toyota",
                "model": "Van",
                "year": 2021,
                "capacity": 6,
                "status": "in_use",
            },
        )
        v3, _ = Vehicle.objects.update_or_create(
            license_plate="BA-2001",
            defaults={
                "business_unit": resort,
                "make": "Hyundai",
                "model": "Staria",
                "year": 2023,
                "capacity": 7,
                "status": "available",
            },
        )

        d_profile, _ = DriverProfile.objects.update_or_create(
            user=u_driver,
            defaults={
                "license_number": "DL-998877",
                "phone": "9800000001",
                "is_available": True,
            },
        )

        td1, _ = TrackingDevice.objects.update_or_create(
            device_id="TRK-1001",
            defaults={"vehicle": v1, "is_connected": True, "last_seen": _now()},
        )
        td2, _ = TrackingDevice.objects.update_or_create(
            device_id="TRK-1002",
            defaults={"vehicle": v2, "is_connected": True, "last_seen": _now()},
        )

        # Simulated GPS positions (Kathmandu approx)
        GPSPosition.objects.all().delete()
        base_lat, base_lng = 27.7172, 85.3240
        for i in range(6):
            GPSPosition.objects.create(
                vehicle=v1,
                latitude=base_lat + (i * 0.0015),
                longitude=base_lng + (i * 0.0012),
                recorded_at=now - timedelta(minutes=30 - i * 5),
                simulated=True,
                speed=24.5 + i,
            )

        VehicleAssignment.objects.create(
            vehicle=v2, driver=d_profile, assigned_at=now - timedelta(hours=2),
        )
        v2.status = "in_use"
        v2.save(update_fields=["status"])

        self.stdout.write("Fleet data seeded.")

        # ---- NEMT ----------------------------------------------------------
        from nemt.models import TransportRequest, Trip

        TransportRequest.objects.all().delete()
        Trip.objects.all().delete()
        req = TransportRequest.objects.create(
            reference="NMT-2026-0001",
            business_unit=health,
            patient_name="Mr. Bikram Thapa",
            pickup_location="City Hospital, Kathmandu",
            dropoff_location="Home Care Residence, Baneshwor",
            pickup_time=now + timedelta(hours=1),
            status=TransportRequest.STATUS_COMPLETED,
            created_by=u_hc,
            assigned_driver=d_profile,
            assigned_vehicle=v2,
        )
        Trip.objects.create(
            request=req,
            driver=d_profile,
            vehicle=v2,
            status="completed",
            start_time=now - timedelta(hours=2),
            pickup_time=now - timedelta(hours=2) + timedelta(minutes=20),
            dropoff_time=now - timedelta(hours=1),
            end_time=now - timedelta(hours=1) + timedelta(minutes=10),
        )

        self.stdout.write("NEMT data seeded.")

        # ---- Payroll -------------------------------------------------------
        # Payroll is calculated from salary structures and attendance only.
        from payroll.models import PayrollRun, SalaryStructure
        from payroll.services import PayrollError, calculate_payroll

        PayrollRun.objects.filter(
            reference__in=["PAY-HEALTH-DEMO", "PAY-RESORT-DEMO"]
        ).delete()
        for index, employee in enumerate(
            Employee.objects.select_related("business_unit").order_by("employee_id")
        ):
            base = 48000 if employee.business_unit_id == health.pk else 36000
            SalaryStructure.objects.update_or_create(
                employee=employee,
                defaults={
                    "business_unit": employee.business_unit,
                    "basic_salary": base + (index % 5) * 1500,
                    "housing_allowance": 4000,
                    "transport_allowance": 2500,
                    "other_allowance": 1500,
                    "tax_rate_percent": 10,
                    "other_deduction": 500,
                    "is_active": True,
                },
            )
        period_end = today
        period_start = today.replace(day=1)
        for unit, reference in (
            (health, "PAY-HEALTH-DEMO"),
            (resort, "PAY-RESORT-DEMO"),
        ):
            try:
                calculate_payroll(
                    division=unit,
                    period_start=period_start,
                    period_end=period_end,
                    created_by=u_hr,
                    reference=reference,
                )
            except PayrollError as exc:  # pragma: no cover - configuration guard
                self.stdout.write(f"Payroll seed skipped for {unit.code}: {exc}")

        # ---- Transport costs ----------------------------------------------
        from nemt.models import RideCostEstimate

        RideCostEstimate.objects.update_or_create(
            reference="RCE-2026-0001",
            defaults={
                "business_unit": health,
                "transport_request": req,
                "distance_km": Decimal("12.5"),
                "duration_minutes": 45,
                "base_fee": Decimal("250.00"),
                "per_km_rate": Decimal("45.00"),
                "driver_hourly_rate": Decimal("300.00"),
                "tolls": Decimal("100.00"),
                "created_by": u_fleet,
            },
        )
        RideCostEstimate.objects.update_or_create(
            reference="RCE-2026-0002",
            defaults={
                "business_unit": resort,
                "distance_km": Decimal("8"),
                "duration_minutes": 30,
                "base_fee": Decimal("200.00"),
                "per_km_rate": Decimal("40.00"),
                "driver_hourly_rate": Decimal("280.00"),
                "tolls": Decimal("0.00"),
                "created_by": u_fleet,
            },
        )

        self.stdout.write("Payroll and transport cost data seeded.")

        # ---- Inventory -----------------------------------------------------
        from inventory.models import (
            Location,
            Product,
            ProductBatch,
            StockIssue,
            StockIssueLine,
            StockReceipt,
            StockReceiptLine,
            StockTransfer,
            StockTransferLine,
            StockMovement,
        )

        # Delete in dependency order so re-running the seed is safe.
        DeliveryLineItem = __import__(
            "medicine_delivery.models", fromlist=["DeliveryLineItem"]
        ).DeliveryLineItem
        DeliveryRequest = __import__(
            "medicine_delivery.models", fromlist=["DeliveryRequest"]
        ).DeliveryRequest
        DeliveryLineItem.objects.all().delete()
        DeliveryRequest.objects.all().delete()
        StockMovement.objects.all().delete()
        StockReceiptLine.objects.all().delete()
        StockReceipt.objects.all().delete()
        StockIssueLine.objects.all().delete()
        StockIssue.objects.all().delete()
        StockTransferLine.objects.all().delete()
        StockTransfer.objects.all().delete()
        ProductBatch.objects.all().delete()
        Product.objects.all().delete()

        loc_pharm, _ = Location.objects.update_or_create(
            name="Main Pharmacy", business_unit=health,
            defaults={"type": "storage", "is_active": True},
        )
        loc_ward, _ = Location.objects.update_or_create(
            name="Ward A", business_unit=health,
            defaults={"type": "ward", "is_active": True},
        )
        loc_kitchen, _ = Location.objects.update_or_create(
            name="Kitchen Pantry", business_unit=resort,
            defaults={"type": "storage", "is_active": True},
        )
        loc_store, _ = Location.objects.update_or_create(
            name="Main Store", business_unit=resort,
            defaults={"type": "storage", "is_active": True},
        )

        def _product(code, name, category, bu, unit, min_qty, perishable,
                     barcode=None, batch_tracking=False):
            return Product.objects.update_or_create(
                sku=code,
                defaults={
                    "name": name,
                    "category": category,
                    "business_unit": bu,
                    "unit": unit,
                    "min_stock": min_qty,
                    "is_perishable": perishable,
                    "barcode": barcode,
                    "batch_tracking_required": batch_tracking,
                    "is_active": True,
                },
            )[0]

        p_paracetamol = _product("MED-001", "Paracetamol 500mg", "Medicine", health, "tablet", 100, False,
                                 barcode="8901234567890", batch_tracking=True)
        p_insulin = _product("MED-002", "Insulin Glargine 100U/ml", "Medicine", health, "vial", 20, True,
                             barcode="8901234567891", batch_tracking=True)
        p_bandage = _product("MED-003", "Gauze Bandage 4 inch", "Consumable", health, "piece", 200, False,
                             barcode="8901234567892", batch_tracking=False)
        p_rice = _product("RES-001", "Premium Rice 25kg", "Food Ingredient", resort, "bag", 50, True,
                          barcode="8901234567893", batch_tracking=True)
        p_oil = _product("RES-002", "Cooking Oil 5L", "Food Ingredient", resort, "bottle", 40, True,
                         barcode="8901234567894", batch_tracking=True)
        p_detergent = _product("RES-003", "Laundry Detergent 5kg", "Cleaning Product", resort, "packet", 30, False,
                               barcode="8901234567895", batch_tracking=False)
        p_coffee = _product("RES-004", "Premium Coffee Beans 1kg", "Food Ingredient", resort, "bag", 20, True,
                            barcode="8901234567896", batch_tracking=True)
        p_soap = _product("RES-005", "Guest Soap 400g", "Housekeeping", resort, "piece", 100, False,
                          barcode="8901234567897", batch_tracking=False)

        def _batch(product, batch, expiry, qty, status="usable", cost=100):
            return ProductBatch.objects.update_or_create(
                product=product,
                batch_number=batch,
                defaults={
                    "expiry_date": expiry,
                    "quantity_received": qty,
                    "quantity_remaining": qty,
                    "unit_cost": cost,
                    "status": status,
                },
            )[0]

        today = _now().date()
        _batch(p_paracetamol, "PCT-2026-001", today + timedelta(days=730), 5000, cost=8)
        b_insulin_good = _batch(p_insulin, "INS-2026-001", today + timedelta(days=120), 50, cost=1200)
        _batch(p_insulin, "INS-EXPIRED", today - timedelta(days=30), 5, status="expired", cost=1200)
        _batch(p_bandage, "BND-2026-001", today + timedelta(days=730), 2000, cost=12)
        b_rice = _batch(p_rice, "RICE-2026-001", today + timedelta(days=90), 100, cost=900)
        _batch(p_oil, "OIL-2026-001", today + timedelta(days=60), 80, cost=750)
        _batch(p_detergent, "DET-2026-001", today + timedelta(days=730), 60, cost=450)
        _batch(p_coffee, "COF-2026-001", today + timedelta(days=180), 50, cost=2000)
        _batch(p_soap, "SOAP-2026-001", today + timedelta(days=730), 500, cost=50)

        self.stdout.write("Inventory seeded.")

        # ---- Medicine delivery ---------------------------------------------
        from medicine_delivery.models import DeliveryLineItem, DeliveryRequest

        DeliveryRequest.objects.all().delete()
        delreq = DeliveryRequest.objects.create(
            reference="DEL-2026-0001",
            business_unit=health,
            recipient_name="Ms. Sunita Gurung",
            recipient_address="Home Care Residence, Baneshwor, Kathmandu",
            status=DeliveryRequest.STATUS_DELIVERED,
            created_by=u_inv,
            assigned_driver=d_profile,
            assigned_vehicle=v1,
        )
        DeliveryLineItem.objects.create(
            delivery=delreq,
            product_batch=b_insulin_good,
            quantity_reserved=2,
            quantity_delivered=2,
        )
        b_insulin_good.quantity_remaining = 48
        b_insulin_good.save(update_fields=["quantity_remaining"])

        # Pending assigned trip for the driver mobile demo.
        from nemt.models import TransportRequest, Trip as NEMTTrip
        pend_req = TransportRequest.objects.create(
            reference="NMT-2026-0002",
            business_unit=health,
            patient_name="Ms. Anjali Devi",
            pickup_location="City Hospital, Kathmandu",
            dropoff_location="Home Care Residence, Baneshwor",
            pickup_time=now + timedelta(hours=2),
            status=TransportRequest.STATUS_ASSIGNED,
            created_by=u_hc,
            assigned_driver=d_profile,
            assigned_vehicle=v2,
        )
        NEMTTrip.objects.create(
            request=pend_req,
            driver=d_profile,
            vehicle=v2,
            status=NEMTTrip.STATUS_ASSIGNED,
        )

        self.stdout.write("Sample data seeded successfully.")
        self.stdout.write("Starter credentials: any account above / password 'admin123'")
