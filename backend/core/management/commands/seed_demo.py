"""Idempotent demo-account seeding for HOMS.

Creates (or safely updates) demo accounts for the six standard roles:

  Super Admin, Resort Inventory Manager, Pharmacy Inventory Manager,
  HR Manager, Finance Manager and Staff.

Safety rules (enforced in code):

* Existing users are NEVER deleted and their passwords are NEVER overwritten.
  An existing login keeps whatever password it already has; the command only
  fills a missing role / business unit when safe and reports anything it skips.
* Passwords are freshly generated with Django's secret-backed generator and
  hashed with Django's normal password machinery - they are never stored in
  source code and never appear in defaults of this file.
* Only accounts created by this command get the ``is_demo`` flag, which is the
  single gate for the environment-gated ``/auth/demo-login/`` one-click login
  endpoint. Regular accounts default to ``is_demo=False``.
* Seeding never runs automatically: it only happens through this explicit
  command.

Usage:

  python manage.py seed_demo                 # create/update accounts
  python manage.py seed_demo --show-passwords
  python manage.py seed_demo --adopt-existing   # flag pre-existing demo emails
  python manage.py seed_demo --with-data        # small realistic demo dataset
  python manage.py seed_demo --verify           # report only, no changes

The credentials file (``--output``, default backend/DEMO_CREDENTIALS.txt) lists
generated passwords for accounts THIS RUN CREATED only.
"""

import os
import secrets
import string

from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import BusinessUnit, Department, Employee, Role, User

# (email, first, last, role_code, role_display_name, business_unit_code)
DEMO_ACCOUNTS = [
    ("super@buildakar.com", "Alex", "Super", "super_admin",
     "Super Administrator", None),
    ("invrs@buildakar.com", "Sarah", "Reyes", "resort_inventory_manager",
     "Resort Inventory Manager", "RESORT"),
    ("inv@buildakar.com", "Priya", "Sharma", "healthcare_inventory_manager",
     "Pharmacy Inventory Manager", "HEALTH"),
    ("hr@buildakar.com", "Marisol", "Chen", "hr_manager", "HR Manager", "HR"),
    ("finance@buildakar.com", "David", "Okwu", "accountant", "Finance Manager",
     "FINANCE"),
    ("staff@buildakar.com", "Tom", "Wilson", "employee", "Staff", "RESORT"),
]


def generate_password():
    """Hard-to-guess, validator-approved password generated in memory."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(16))
        try:
            validate_password(candidate)
            return candidate
        except Exception:
            continue


class Command(BaseCommand):
    help = (
        "Create demo accounts for the six standard roles idempotently. Never "
        "deletes records and never overwrites an existing password."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--show-passwords", action="store_true",
            help="Print generated passwords to stdout instead of the output file.",
        )
        parser.add_argument(
            "--output", default="DEMO_CREDENTIALS.txt",
            help="Credentials file for newly created accounts (default: DEMO_CREDENTIALS.txt).",
        )
        parser.add_argument(
            "--adopt-existing", action="store_true",
            help=(
                "Flag pre-existing users with a seed email as demo (enables "
                "one-click demo login for them). Passwords still never change."
            ),
        )
        parser.add_argument(
            "--with-data", action="store_true",
            help="Also populate a small realistic demonstration dataset.",
        )
        parser.add_argument(
            "--verify", action="store_true",
            help="Only report the state of demo accounts; change nothing.",
        )

    # ---------------------------------------------------------------- state

    def _ensure_reference_data(self):
        for code, name in [
            ("RESORT", "Resort Operations"),
            ("HEALTH", "Healthcare Operations"),
            ("HR", "Human Resources"),
            ("FINANCE", "Finance and Accounting"),
            ("TRANSPORT", "Transportation and Ride Management"),
            ("ATTENDANCE", "Attendance and Workforce Management"),
            ("ADMIN", "Enterprise Administration"),
        ]:
            BusinessUnit.objects.get_or_create(code=code, defaults={"name": name})

    def _role_for(self, role_code, role_name, unit_code):
        role, created = Role.objects.get_or_create(
            code=role_code, defaults={"name": role_name, "business_unit": (
                BusinessUnit.objects.get(code=unit_code) if unit_code else None
            )},
        )
        if not created and not role.is_active:
            role.is_active = True
            role.save(update_fields=["is_active"])
        return role, created

    def _safe_fill(self, user, role, unit_code):
        """Fill missing role/unit on an existing user; never overwrite real ones."""
        notes = []
        if user.role_id is None:
            user.role = role
            notes.append("role assigned")
        elif user.role_id != role.pk:
            notes.append(f"existing role '{user.role.code}' kept")
        if unit_code and user.business_unit_id is None:
            user.business_unit = BusinessUnit.objects.get(code=unit_code)
            notes.append("business unit assigned")
        return notes

    # ---------------------------------------------------------------- handle

    def handle(self, *args, **options):
        """Seed inside one atomic DB transaction, then write credentials only
        after the transaction has committed successfully."""
        with transaction.atomic():
            results = self._seed_accounts(*args, **options)
        if not options["verify"]:
            self._handle_credentials(
                results, options["show_passwords"], options["output"]
            )
            if options["with_data"]:
                with transaction.atomic():
                    self._seed_demo_data()
            self.stdout.write(self.style.SUCCESS("Demo seeding complete."))

    def _seed_accounts(self, *args, **options):
        show_passwords = bool(options["show_passwords"])
        verify_only = bool(options["verify"])
        self.stdout.write(self.style.MIGRATE_HEADING("HOMS demo-account seeding"))

        self._ensure_reference_data()
        results = []
        report_lines = []

        for email, first, last, role_code, role_name, unit_code in DEMO_ACCOUNTS:
            role, role_created = self._role_for(role_code, role_name, unit_code)
            user = User.objects.filter(email__iexact=email).first()

            if verify_only:
                if user is None:
                    report_lines.append(f"  MISSING  {email} ({role_name})")
                else:
                    unit = user.business_unit.code if user.business_unit_id else "-"
                    flag = "demo" if user.is_demo else "regular"
                    report_lines.append(
                        f"  LIVE     {email} role={user.role.code if user.role else '-'} "
                        f"unit={unit} flag={flag}"
                    )
                continue

            if user is None:
                password = generate_password()
                unit = BusinessUnit.objects.get(code=unit_code) if unit_code else None
                user = User.objects.create_user(
                    username=email.split("@")[0],
                    email=email,
                    password=password,
                    first_name=first,
                    last_name=last,
                    role=role,
                    business_unit=unit,
                    is_active=True,
                    is_approved=True,
                    is_demo=True,
                    is_staff=(role_code == "super_admin"),
                )
                results.append((user, password))
                self.stdout.write(self.style.SUCCESS(f"  CREATED  {email} ({role_name})"))
                self._link_employee(user, unit_code)
                continue

            # ---- existing account: identity and password are never touched.
            changes = ["password left untouched"]
            if role_created:
                changes.append(f"role '{role_code}' created")
            filled = self._safe_fill(user, role, unit_code)
            if filled:
                user.save(update_fields=["role", "business_unit"])
                changes.extend(filled)
            if not user.is_demo:
                if options["adopt_existing"]:
                    user.is_demo = True
                    user.save(update_fields=["is_demo"])
                    changes.append("flagged is_demo (--adopt-existing)")
                else:
                    changes.append("is_demo remains False (use --adopt-existing)")
            if not user.is_active or not user.is_approved:
                changes.append(
                    "ACTIVE=(" + ("enabled" if user.is_active else "disabled") + ") "
                    + ("approved" if user.is_approved else "NOT approved")
                )
            self.stdout.write(f"  EXISTS   {email}: {'; '.join(changes)}")

        if verify_only:
            self.stdout.write("\n".join(report_lines) or "  No change requested.")
            return results

        return results

    def _link_employee(self, user, unit_code):
        """Give staff/inventory/HR/finance demo users an HR employee record."""
        if not unit_code:
            return
        unit = BusinessUnit.objects.get(code=unit_code)
        designation = user.get_full_name()
        dept, _ = Department.objects.get_or_create(
            name="Administration", business_unit=unit,
        )
        base = f"EMP-{user.pk:04d}"
        employee_id = base
        n = 1
        while Employee.objects.filter(employee_id=employee_id).exists():
            n += 1
            employee_id = f"{base}-{n}"  # never mutate an existing record
        Employee.objects.get_or_create(
            user=user,
            defaults={
                "employee_id": employee_id,
                "business_unit": unit,
                "department": dept,
                "designation": designation,
                "hire_date": None,
            },
        )

    def _handle_credentials(self, results, show_passwords, output):
        fresh = [(u, p) for u, p in results if p]
        if not fresh:
            self.stdout.write(
                "No new accounts were created - no credentials were generated."
            )
            return
        rows = [f"{u.email}  {p}" for u, p in fresh]
        if show_passwords:
            self.stdout.write("\n".join(f"  {r}" for r in rows))
            return
        path = os.path.abspath(output)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("HOMS demo credentials - generated by `manage.py seed_demo`.\n")
            fh.write("Passwords below apply ONLY to accounts this run created.\n\n")
            fh.write("\n".join(rows) + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self.stdout.write(f"  Credentials written to {path} (not committed to git).")

    # ----------------------------------------------------------------- data

    def _seed_demo_data(self):
        """Small, get_or_create-only demo dataset that exercises isolation."""
        from inventory.models import Product, Supplier

        dataset = [
            ("RESORT", [("RES-BEVERAGE-01", "Beverages", "each", False, 10),
                        ("RES-TOWEL-01", "Bath Towels", "each", False, 5)]),
            ("HEALTH", [("HEA-ASPIRIN-01", "Aspirin 100mg", "box", True, 2),
                        ("HEA-SYRINGE-01", "Syringes 5ml", "box", True, 1)]),
        ]
        for code, products in dataset:
            unit = BusinessUnit.objects.get(code=code)
            supplier, created = Supplier.objects.get_or_create(
                name=f"{unit.name} Demo Supplier",
                business_unit=unit,
                defaults={
                    "code": f"SUP-{code[:4]}",
                    "contact_person": "Demo Supplier",
                    "phone": "+1-555-0100",
                    "email": f"demo.{code.lower()}@homs-example.com",
                    "is_active": True,
                },
            )
            for sku, name, unit_of_measure, perishable, min_stock in products:
                Product.objects.get_or_create(
                    sku=sku, business_unit=unit,
                    defaults={
                        "name": name, "category": "Demo", "unit": unit_of_measure,
                        "is_perishable": perishable, "min_stock": min_stock,
                        "is_active": True,
                    },
                )
        self.stdout.write("  Demo dataset ensured (get_or_create only).")
