"""Development seed data command for HOMS.

Populates representative sample records for divisions, roles, permissions,
employees, inventory, and other reference data.

RUN ONLY in development or test environments. Never seed default passwords into production.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
import string
import random


def random_string(length=8):
    """Generate a random string of fixed length."""
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(length))


def random_decimal(max_digits=14, decimal_places=2):
    """Generate a random decimal value."""
    integer_part = random.randint(0, 9999)
    decimal_part = random.randint(0, 99)
    return Decimal(f"{integer_part}.{decimal_part:02d}")


class Command(BaseStyle):
    help = "Seed development database with reference data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--env",
            type=str,
            choices=["development", "test", "production"],
            default="development",
            help="Environment to seed data for",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        environment = options["env"]

        if environment == "production":
            self.stderr.write(
                self.style.ERROR("Production seeding is disabled for safety.")
            )
            return

        self.stdout.write(f"Seeding data for environment: {environment}")

        # 1. Create Business Units / Divisions
        from core.models import BusinessUnit

        division_data = [
            ("RESORT", "Resort Operations"),
            ("HEALTH", "Healthcare Operations"),
            ("HR", "Human Resources"),
            ("FINANCE", "Finance and Accounting"),
            ("TRANSPORT", "Transportation and Ride Management"),
            ("ATTENDANCE", "Attendance and Workforce Management"),
            ("ADMIN", "Enterprise Administration"),
        ]

        for code, name in division_data:
            BusinessUnit.objects.get_or_create(code=code, defaults={"name": name})

        self.stdout.write(f"  Created {BusinessUnit.objects.count()} business units")

        # 2. Create Roles
        from core.models import Role

        Role.objects.get_or_create(code="super_admin", defaults={"name": "Super Administrator"})
        Role.objects.get_or_create(code="hr_manager", defaults={"name": "HR Manager"})
        Role.objects.get_or_create(code="resort_inventory_manager", defaults={"name": "Resort Inventory Manager"})
        Role.objects.get_or_create(code="healthcare_inventory_manager", defaults={"name": "Pharmacy Inventory Manager"})
        Role.objects.get_or_create(code="finance_manager", defaults={"name": "Finance Manager"})
        Role.objects.get_or_create(code="attendance_manager", defaults={"name": "Attendance Manager"})
        Role.objects.get_or_create(code="transportation_manager", defaults={"name": "Transportation Manager"})
        Role.objects.get_or_create(code="staff_member", defaults={"name": "Staff Member"})

        self.stdout.write(f"  Created {Role.objects.count()} roles")

        # 3. Assign roles to business units (division-scoped roles)
        from core.models import BusinessUnit

        resort_bu = BusinessUnit.objects.get(code="RESORT")
        health_bu = BusinessUnit.objects.get(code="HEALTH")
        hr_bu = BusinessUnit.objects.get(code="HR")
        finance_bu = BusinessUnit.objects.get(code="FINANCE")
        transport_bu = BusinessUnit.objects.get(code="TRANSPORT")
        attendance_bu = BusinessUnit.objects.get(code="ATTENDANCE")
        admin_bu = BusinessUnit.objects.get(code="ADMIN")

        # Resort inventory manager scoped to resort
        resort_role, _ = Role.objects.get_or_create(
            code="resort_inventory_manager", defaults={"name": "Resort Inventory Manager"}
        )
        resort_role.business_unit = resort_bu
        resort_role.save()

        # Healthcare inventory manager scoped to healthcare
        health_role, _ = Role.objects.get_or_create(
            code="healthcare_inventory_manager", defaults={"name": "Pharmacy Inventory Manager"}
        )
        health_role.business_unit = health_bu
        health_role.save()

        # Finance manager scoped to finance
        finance_role, _ = Role.objects.get_or_create(
            code="finance_manager", defaults={"name": "Finance Manager"}
        )
        finance_role.business_unit = finance_bu
        finance_role.save()

        # Attendance manager scoped to attendance
        attendance_role, _ = Role.objects.get_or_create(
            code="attendance_manager", defaults={"name": "Attendance Manager"}
        )
        attendance_role.business_unit = attendance_bu
        attendance_role.save()

        # Transportation manager scoped to transport
        transport_role, _ = Role.objects.get_or_create(
            code="transportation_manager", defaults={"name": "Transportation Manager"}
        )
        transport_role.business_unit = transport_bu
        transport_role.save()

        self.stdout.write(f"  Linked roles to business units")

        # 4. Create Employees
        from core.models import Employee, Department
        from nemt.models import Vehicle, DriverProfile

        # Create departments for each business unit
        dept_codes = {
            "RESORT": ["Front Desk", "Housekeeping", "Food & Beverage", "Maintenance"],
            "HEALTH": ["Pharmacy", "Clinical", "Administration"],
            "HR": ["Recruitment", "Payroll", "Training"],
            "FINANCE": ["Accounting", "Accounts Payable", "Financial Planning"],
            "TRANSPORT": ["Fleet Operations", "Driver Services"],
            "ATTENDANCE": ["Attendance Operations"],
            "ADMIN": ["Executive", "IT", "Operations"],
        }

        departments = {}
        for bu_code, dept_list in dept_codes.items():
            bu = BusinessUnit.objects.get(code=bu_code)
            for dept_name in dept_list:
                dept, _ = Department.objects.get_or_create(
                    name=dept_name, business_unit=bu
                )
                departments[(bu_code, dept_name)] = dept

        # Create sample employees
        employee_data = [
            # Format: (user_email, employee_id, department, business_unit_code, role_code)
            ("john.smith@homs.com", "EMP001", "Human Resources", "HR", "hr_manager"),
            ("jane.doe@homs.com", "EMP002", "Finance", "FINANCE", "finance_manager"),
            ("robert.johnson@homs.com", "EMP003", "Front Desk", "RESORT", "resort_inventory_manager"),
            ("mary.williams@homs.com", "EMP004", "Pharmacy", "HEALTH", "healthcare_inventory_manager"),
            ("david.brown@homs.com", "EMP005", "Fleet Operations", "TRANSPORT", "transportation_manager"),
            ("lisa.cooper@homs.com", "EMP006", "Attendance Operations", "ATTENDANCE", "attendance_manager"),
        ]

        from core.models import User

        for email, emp_id, dept_name, bu_code, role_code in employee_data:
            bu = BusinessUnit.objects.get(code=bu_code)
            dept = departments.get((bu_code, dept_name))

            # Create or get user
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": email.split("@")[0],
                    "is_active": True,
                    "is_approved": True,
                },
            )

            # Create employee linked to user
            employee, created = Employee.objects.get_or_create(
                user=user,
                defaults={
                    "employee_id": emp_id,
                    "department": dept,
                    "business_unit": bu,
                    "designation": email.split("@")[0].replace(".", " ").title(),
                    "hire_date": "2024-01-01",
                },
            )

            if created:
                self.stdout.write(f"  Created employee: {employee}")

        self.stdout.write(f"  Created {Employee.objects.count()} employees")

        # 5. Create sample inventory products per division
        from inventory.models import Product, Supplier

        # Create sample products for each division - using only fields that exist on the Product model
        product_data = [
            # (product_name, business_unit_code, unit_of_measure, is_perishable, min_stock)
            ("Beverages", "RESORT", "each", False, 10),
            ("Towels", "RESORT", "each", False, 5),
            ("Disinfectant", "RESORT", "bottles", False, 2),
            ("Rice", "RESORT", "kg", False, 5),
            ("Aspirin", "HEALTH", "boxes", True, 1),
            ("Syringes", "HEALTH", "boxes", True, 1),
            ("Vitamins", "HEALTH", "bottles", True, 2),
            ("Gauze", "HEALTH", "packs", True, 3),
        ]

        for product_name, bu_code, unit, is_perishable, min_stock in product_data:
            bu = BusinessUnit.objects.get(code=bu_code)
            product, _ = Product.objects.get_or_create(
                name=product_name,
                business_unit=bu,
                defaults={
                    "sku": product_name[:10].upper(),
                    "category": product_name[:10].upper(),
                    "unit": unit,
                    "is_perishable": is_perishable,
                    "min_stock": min_stock,
                    "is_active": True,
                },
            )

            # Create a supplier - using field names that exist on Supplier model
            supplier, _ = Supplier.objects.get_or_create(
                name=f"{product_name} Supplies",
                business_unit=bu,
                defaults={
                    "code": product_name[:10].upper(),
                    "contact_person": f"Contact {random_string(6)}",
                    "phone": f"+1-555-{random_string(4)}",
                    "email": f"contact@{product_name.lower().replace(' ', '')}.com",
                    "is_active": True,
                },
            )

            self.stdout.write(f"  Created product: {product} from {supplier}")

        self.stdout.write(f"  Created inventory data")

        # 6. Create sample attendance shifts
        from attendance.models import Shift

        # Create sample shifts with required start_time and end_time
        shift_times = [
            ("08:00", "16:00"),  # Day shift
            ("16:00", "24:00"),  # Night shift
            ("00:00", "08:00"),  # Overnight shift
        ]

        for bu_code in ["RESORT", "HEALTH", "ATTENDANCE"]:
            bu = BusinessUnit.objects.get(code=bu_code)
            for i in range(3):
                start_hour = (i * 2) % 3 + 6  # 6, 7, 8
                end_hour = (start_hour + 8) % 24
                shift, _ = Shift.objects.get_or_create(
                    name=f"{bu_code} Shift {i+1}",
                    business_unit=bu,
                    defaults={
                        "start_time": f"{start_hour:02d}:00",
                        "end_time": f"{end_hour:02d}:00",
                    },
                )

        self.stdout.write(f"  Created attendance shifts")

        # 7. Create sample ride requests (NEMT)
        from nemt.models import RideRequest, RideAssignment, RideRecord, RideCostEstimate, Trip, Vehicle, DriverProfile

        # Create a vehicle and driver if they don't exist
        vehicle, _ = Vehicle.objects.get_or_create(
            plate_number="ABC-123",
            defaults={"model": "Sedan", "year": 2024, "capacity": 4},
        )

        driver, _ = DriverProfile.objects.get_or_create(
            name="John Driver",
            defaults={"license_number": "DLR-12345", "phone": "+1-555-0100"},
        )

        # Create ride request
        from core.models import BusinessUnit
        resort_bu = BusinessUnit.objects.get(code="RESORT")

        ride_request, _ = RideRequest.objects.get_or_create(
            reference=f"RIDE{random_string(6).upper()}",
            business_unit=resort_bu,
            rider_name="John Doe",
            pickup_location="Hotel Front Desk",
            dropoff_location="Airport",
            requested_at="2026-01-15T10:00:00Z",
            scheduled_at="2026-01-15T10:30:00Z",
            status="requested",
            assigned_driver=driver,
            assigned_vehicle=vehicle,
        )

        # Create trip linked to ride request
        trip, _ = Trip.objects.get_or_create(
            status="assigned",
            start_time="2026-01-15T10:15:00Z",
            pickup_time="2026-01-15T10:15:00Z",
            dropoff_time="2026-01-15T11:00:00Z",
            end_time="2026-01-15T11:30:00Z",
            notes="Airport transfer",
            driver=driver,
            request=ride_request,
            vehicle=vehicle,
        )

        # Create ride assignment
        assignment, _ = RideAssignment.objects.get_or_create(
            ride_request=ride_request,
            driver=driver,
            vehicle=vehicle,
        )

        # Create ride record
        ride_record, _ = RideRecord.objects.get_or_create(
            ride_request=ride_request,
            driver=driver,
            vehicle=vehicle,
            status="completed",
            pickup_time="2026-01-15T10:15:00Z",
            dropoff_time="2026-01-15T11:00:00Z",
            completed_at="2026-01-15T11:05:00Z",
        )

        # Create fare estimate
        fare_estimate, _ = RideCostEstimate.objects.get_or_create(
            ride_request=ride_request,
            base_fare=Decimal("15.00"),
            distance_km=5.0,
            waiting_time_min=10,
            total_cost=Decimal("25.00"),
            fare_status="shared",
        )

        self.stdout.write(f"  Created NEMT ride data")

        self.stdout.write(self.style.SUCCESS("Seed data completed successfully!"))