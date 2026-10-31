"""Tests for demo-account seeding, the gated demo-login endpoints, and the
resort/pharmacy division isolation enforced for the six demo roles."""

import io
import os
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import BusinessUnit, Employee, Role, User
from inventory.models import Product

DEMO_EMAILS = [
    "super@buildakar.com",
    "invrs@buildakar.com",
    "inv@buildakar.com",
    "hr@buildakar.com",
    "finance@buildakar.com",
    "staff@buildakar.com",
]


class SeedDemoCommandTests(TestCase):
    """Idempotency, password safety and correct role/unit assignment."""

    def seed(self, *args):
        """Runs the command; returns the credentials-file text, or None when no
        new accounts were created (idempotent reruns generate nothing)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "credentials.txt")
            call_command("seed_demo", "--output", out, *args, stdout=io.StringIO())
            if not os.path.exists(out):
                return None
            with open(out, encoding="utf-8") as fh:
                return fh.read()

    def test_creates_six_accounts_once_and_is_idempotent(self):
        credentials = self.seed()
        self.assertIsNotNone(credentials, "First run must generate credentials.")
        self.assertEqual(User.objects.filter(email__in=DEMO_EMAILS).count(), 6)
        # Second run creates nothing new and reuses existing rows.
        before = list(User.objects.filter(email__in=DEMO_EMAILS))
        rerun_credentials = self.seed()
        after = list(User.objects.filter(email__in=DEMO_EMAILS))
        self.assertIsNone(
            rerun_credentials,
            "Idempotent reruns must not generate credentials again.",
        )
        self.assertEqual(
            [u.pk for u in before],
            [u.pk for u in after],
            "Re-running seed_demo must never recreate accounts.",
        )

    def test_roles_and_units_assigned(self):
        self.seed()
        expected = {
            "super@buildakar.com": ("super_admin", None),
            "invrs@buildakar.com": ("resort_inventory_manager", "RESORT"),
            "inv@buildakar.com": ("healthcare_inventory_manager", "HEALTH"),
            "hr@buildakar.com": ("hr_manager", "HR"),
            "finance@buildakar.com": ("accountant", "FINANCE"),
            "staff@buildakar.com": ("employee", "RESORT"),
        }
        for email, (role_code, unit_code) in expected.items():
            with self.subTest(email=email):
                user = User.objects.get(email=email)
                self.assertEqual(user.role_code, role_code)
                self.assertEqual(user.business_unit_code, unit_code)
                self.assertTrue(user.role.is_active)

    def test_passwords_hashed_and_not_equal_across_accounts(self):
        content = self.seed()
        pws = []
        lines = [line.strip() for line in content.splitlines() if "@" in line]
        self.assertEqual(len(lines), 6)
        for line in lines:
            email, password = [part.strip() for part in line.split()]
            user = User.objects.get(email=email)
            self.assertTrue(user.check_password(password))
            self.assertNotEqual(user.password, password)
            pws.append(password)
        self.assertEqual(len(set(pws)), 6, "Each account must get its own password.")

    def test_existing_account_password_never_overwritten(self):
        User.objects.create_user(
            username="hr_exists", email="hr@buildakar.com", password="real-password-77",
        )
        self.seed()
        user = User.objects.get(email="hr@buildakar.com")
        self.assertTrue(user.check_password("real-password-77"))
        self.assertFalse(user.is_demo, "Pre-existing accounts only become demo with --adopt-existing.")

    def test_existing_role_is_kept_not_overwritten(self):
        other = Role.objects.create(code="fleet_manager", name="Fleet Manager")
        unit = BusinessUnit.objects.get_or_create(
            code="RESORT", defaults={"name": "Resort"},
        )[0]
        User.objects.create_user(
            username="inv", email="inv@buildakar.com", password="whatever-1",
            role=other, business_unit=unit,
        )
        self.seed()
        user = User.objects.get(email="inv@buildakar.com")
        self.assertEqual(user.role_code, "fleet_manager")

    def test_employee_record_created_for_scoped_accounts(self):
        self.seed()
        self.assertEqual(
            Employee.objects.filter(user__email="staff@buildakar.com").count(), 1
        )
        self.assertFalse(
            Employee.objects.filter(user__email="super@buildakar.com").exists()
        )


@override_settings(DEMO_LOGIN=True)
class DemoLoginEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=cls.open_out())

    @classmethod
    def open_out(cls):
        import io

        return io.StringIO()

    def setUp(self):
        self.client = APIClient()

    def test_demo_accounts_lists_six_without_passwords(self):
        res = self.client.get("/api/v1/auth/demo-accounts/")
        self.assertEqual(res.status_code, 200)
        emails = [item["email"] for item in res.data]
        self.assertEqual(sorted(emails), sorted(DEMO_EMAILS))
        keys = {key for item in res.data for key in item}
        self.assertNotIn("password", keys)
        labels = {item["email"]: item["role_code"] for item in res.data}
        self.assertEqual(labels["super@buildakar.com"], "super_admin")
        self.assertEqual(labels["invrs@buildakar.com"], "resort_inventory_manager")
        self.assertEqual(labels["inv@buildakar.com"], "healthcare_inventory_manager")
        self.assertEqual(labels["finance@buildakar.com"], "accountant")

    def test_demo_login_works_and_returns_valid_tokens(self):
        res = self.client.post(
            "/api/v1/auth/demo-login/", {"email": "invrs@buildakar.com"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertIn("user", res.data)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + res.data["access"])
        me = self.client.get("/api/v1/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["email"], "invrs@buildakar.com")

    def test_demo_login_rejects_non_demo_and_unknown_accounts(self):
        User.objects.create_user(
            username="real", email="real@buildakar.com", password="Super-Secret-99"
        )
        for email in ["real@buildakar.com", "unknown@buildakar.com"]:
            with self.subTest(email=email):
                res = self.client.post(
                    "/api/v1/auth/demo-login/", {"email": email}, format="json"
                )
                self.assertEqual(res.status_code, 403)

    def test_demo_login_rejects_inactive_or_unapproved(self):
        user = User.objects.get(email="hr@buildakar.com")
        user.is_approved = False
        user.save(update_fields=["is_approved"])
        res = self.client.post(
            "/api/v1/auth/demo-login/", {"email": user.email}, format="json"
        )
        self.assertEqual(res.status_code, 403)
        user.is_approved = True
        user.is_active = False
        user.save(update_fields=["is_active"])
        res = self.client.post(
            "/api/v1/auth/demo-login/", {"email": user.email}, format="json"
        )
        self.assertEqual(res.status_code, 403)

    @override_settings(DEMO_LOGIN=False)
    def test_demo_login_disabled_by_default(self):
        res = self.client.post(
            "/api/v1/auth/demo-login/", {"email": "hr@buildakar.com"}, format="json"
        )
        self.assertEqual(res.status_code, 404)
        listing = self.client.get("/api/v1/auth/demo-accounts/")
        self.assertEqual(listing.status_code, 404)


@override_settings(DEMO_LOGIN=True)
class DemoDivisionIsolationTests(TestCase):
    """Seed data in both divisions; each demo role may only see its own."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=cls.open_out())
        resort = BusinessUnit.objects.get(code="RESORT")
        health = BusinessUnit.objects.get(code="HEALTH")
        Product.objects.create(
            sku="RES-TOOL-01", name="Beach Umbrella", business_unit=resort, unit="each",
        )
        Product.objects.create(
            sku="HEA-MED-01", name="Cough Syrup", business_unit=health, unit="box",
        )

    @classmethod
    def open_out(cls):
        import io

        return io.StringIO()

    def login(self, email):
        client = APIClient()
        res = client.post("/api/v1/auth/demo-login/", {"email": email}, format="json")
        self.assertEqual(res.status_code, 200, f"demo login failed for {email}")
        client.credentials(HTTP_AUTHORIZATION="Bearer " + res.data["access"])
        return client

    def test_resort_manager_sees_only_resort_products(self):
        client = self.login("invrs@buildakar.com")
        res = client.get("/api/v1/inventory/products/")
        self.assertEqual(res.status_code, 200)
        names = [
            product["name"] for product in self._flatten(res.data)
        ]
        self.assertEqual(names, ["Beach Umbrella"])

    def test_pharmacy_manager_sees_only_pharmacy_products(self):
        client = self.login("inv@buildakar.com")
        res = client.get("/api/v1/inventory/products/")
        self.assertEqual(res.status_code, 200)
        names = [
            product["name"] for product in self._flatten(res.data)
        ]
        self.assertEqual(names, ["Cough Syrup"])

    def test_resort_manager_cannot_read_pharmacy_unit_directly(self):
        health = BusinessUnit.objects.get(code="HEALTH")
        client = self.login("invrs@buildakar.com")
        res = client.get("/api/v1/inventory/products/", {"business_unit": health.pk})
        self.assertEqual(res.status_code, 403)

    def test_pharmacy_manager_cannot_request_resort_division(self):
        resort = BusinessUnit.objects.get(code="RESORT")
        client = self.login("inv@buildakar.com")
        res = client.get("/api/v1/inventory/products/", {"business_unit": resort.pk})
        self.assertEqual(res.status_code, 403)

    def test_inventory_managers_cannot_administer_admin_module(self):
        for email in ["invrs@buildakar.com", "inv@buildakar.com"]:
            with self.subTest(email=email):
                client = self.login(email)
                records = self._flatten(client.get("/api/v1/users/").data)
                # Only their own account is visible; no other identities, no
                # cross-division leakage.
                self.assertEqual([record["email"] for record in records], [email])
                other = User.objects.get(email="staff@buildakar.com")
                res = client.patch(
                    f"/api/v1/users/{other.pk}/", {"is_active": False}, format="json"
                )
                self.assertEqual(res.status_code, 403, "Only super_admin may manage accounts.")

    def test_staff_and_hr_role_access_matrix(self):
        hr = self.login("hr@buildakar.com")
        self.assertEqual(hr.get("/api/v1/inventory/products/").status_code, 200)
        records = self._flatten(hr.get("/api/v1/users/").data)
        self.assertEqual([record["email"] for record in records], ["hr@buildakar.com"])

    def test_super_admin_sees_both_divisions(self):
        client = self.login("super@buildakar.com")
        res = client.get("/api/v1/inventory/products/")
        self.assertEqual(res.status_code, 200)
        names = [
            product["name"] for product in self._flatten(res.data)
        ]
        self.assertEqual(sorted(names), ["Beach Umbrella", "Cough Syrup"])

    @staticmethod
    def _flatten(payload):
        """DRF pagination wraps lists; accept both shapes."""
        if isinstance(payload, dict) and "results" in payload:
            return payload["results"]
        return payload
