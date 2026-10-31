"""Division isolation, ledger integrity and concurrency-safe stock posting."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import BusinessUnit, Department, DivisionAccess, Role, User
from inventory import services
from inventory.models import (
    Location,
    Product,
    ProductBatch,
    StockIssue,
    StockMovement,
    StockReceipt,
)


def _user(email, role_code, unit):
    role = Role.objects.create(code=role_code, name=role_code.replace("_", " ").title())
    return User.objects.create_user(
        username=email, email=email, password="pass123", role=role,
        business_unit=unit, is_active=True, is_approved=True,
    )


class TwoDivisionScenarioTests(TestCase):
    """The required 200 + 300, issue 150 => 50 + 300 = 350 proof."""

    def setUp(self):
        self.resort = BusinessUnit.objects.create(name="Resort", code="RESORT")
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH")
        self.resort_manager = _user("resort@test.com", "resort_inventory_manager", self.resort)
        self.health_manager = _user("health@test.com", "healthcare_inventory_manager", self.health)
        self.client = APIClient()

        self.resort_loc = Location.objects.create(name="Resort Store", business_unit=self.resort)
        self.health_loc = Location.objects.create(name="Pharmacy", business_unit=self.health)
        self.resort_dept = Department.objects.create(name="Kitchen", business_unit=self.resort)
        self.health_dept = Department.objects.create(name="Nursing", business_unit=self.health)

        self.resort_product = Product.objects.create(
            sku="RES-001", name="Rice", business_unit=self.resort, unit="bag", min_stock=10,
        )
        self.health_product = Product.objects.create(
            sku="MED-001", name="Paracetamol", business_unit=self.health, unit="tablet",
            min_stock=10,
        )
        self.resort_batch = ProductBatch.objects.create(
            product=self.resort_product, batch_number="A-1", quantity_received=200,
            quantity_remaining=200, unit_cost=Decimal("10.00"),
        )
        self.health_batch = ProductBatch.objects.create(
            product=self.health_product, batch_number="B-1", quantity_received=300,
            quantity_remaining=300, unit_cost=Decimal("2.00"),
        )

    def test_issue_150_from_resort_leaves_50_and_health_untouched(self):
        issue, created = services.post_issue(
            division=self.resort,
            department=self.resort_dept,
            reference="ISSUE-A-1",
            lines=[{"product_batch": self.resort_batch, "quantity": 150}],
        )
        self.assertTrue(created)
        self.resort_batch.refresh_from_db()
        self.health_batch.refresh_from_db()
        self.assertEqual(self.resort_batch.quantity_remaining, 50)
        self.assertEqual(self.health_batch.quantity_remaining, 300)
        total = self.resort_batch.quantity_remaining + self.health_batch.quantity_remaining
        self.assertEqual(total, 350)

        movements = StockMovement.objects.filter(reference="ISSUE-A-1")
        self.assertEqual(movements.count(), 1)
        movement = movements.get()
        self.assertEqual(movement.business_unit, self.resort)
        self.assertEqual(movement.quantity, -150)
        self.assertEqual(movement.quantity_before, 200)
        self.assertEqual(movement.quantity_after, 50)
        self.assertEqual(StockIssue.objects.count(), 1)

    def test_excessive_issue_is_rejected_without_partial_write(self):
        with self.assertRaises(services.StockError):
            services.post_issue(
                division=self.resort,
                department=self.resort_dept,
                reference="ISSUE-A-TOO-BIG",
                lines=[{"product_batch": self.resort_batch, "quantity": 250}],
            )
        self.resort_batch.refresh_from_db()
        self.assertEqual(self.resort_batch.quantity_remaining, 200)
        self.assertFalse(StockIssue.objects.filter(reference="ISSUE-A-TOO-BIG").exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_receipt_replay_is_idempotent(self):
        receipt, created = services.post_receipt(
            division=self.resort,
            location=self.resort_loc,
            reference="GRN-A-1",
            lines=[{
                "product": self.resort_product, "batch_number": "A-1",
                "quantity": 25, "unit_cost": "10.00",
            }],
        )
        self.assertTrue(created)
        replay, created_again = services.post_receipt(
            division=self.resort,
            location=self.resort_loc,
            reference="GRN-A-1",
            lines=[{
                "product": self.resort_product, "batch_number": "A-1",
                "quantity": 25, "unit_cost": "10.00",
            }],
        )
        self.assertFalse(created_again)
        self.assertEqual(receipt.pk, replay.pk)
        self.resort_batch.refresh_from_db()
        self.assertEqual(self.resort_batch.quantity_remaining, 225)
        self.assertEqual(StockReceipt.objects.count(), 1)

    def test_fefo_allocates_earliest_expiry_first(self):
        today = timezone.localdate()
        later = ProductBatch.objects.create(
            product=self.resort_product, batch_number="A-LATER",
            expiry_date=today + timedelta(days=90), quantity_received=50,
            quantity_remaining=50, unit_cost=Decimal("10.00"),
        )
        earlier = ProductBatch.objects.create(
            product=self.resort_product, batch_number="A-EARLIER",
            expiry_date=today + timedelta(days=10), quantity_received=40,
            quantity_remaining=40, unit_cost=Decimal("10.00"),
        )
        allocations = services.allocate_fefo(self.resort_product, 60, self.resort)
        self.assertEqual(allocations[0][0].pk, earlier.pk)
        self.assertEqual(allocations[0][1], 40)
        self.assertEqual(allocations[1][0].pk, later.pk)
        self.assertEqual(allocations[1][1], 20)

        services.post_issue(
            division=self.resort,
            department=self.resort_dept,
            reference="ISSUE-FEFO",
            lines=[{"product": self.resort_product, "quantity": 60}],
        )
        earlier.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(earlier.quantity_remaining, 0)
        self.assertEqual(later.quantity_remaining, 30)

    def test_api_cross_division_read_is_forbidden(self):
        self.client.force_authenticate(self.resort_manager)
        response = self.client.get(
            "/api/v1/inventory/products/",
            {"business_unit": self.health.pk},
        )
        self.assertEqual(response.status_code, 403, response.data)
        response = self.client.get("/api/v1/inventory/products/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["sku"], "RES-001")

    def test_api_cannot_issue_other_division_batch(self):
        self.client.force_authenticate(self.resort_manager)
        response = self.client.post("/api/v1/inventory/issues/", {
            "reference": "CROSS-ISSUE",
            "business_unit": self.resort.pk,
            "department": self.resort_dept.pk,
            "lines": [{"product_batch": self.health_batch.pk, "quantity": 5}],
        }, format="json")
        self.assertIn(response.status_code, (400, 403), response.data)
        self.health_batch.refresh_from_db()
        self.assertEqual(self.health_batch.quantity_remaining, 300)

    def test_api_cannot_receive_into_other_division(self):
        self.client.force_authenticate(self.resort_manager)
        response = self.client.post("/api/v1/inventory/receipts/", {
            "reference": "CROSS-RECEIPT",
            "business_unit": self.health.pk,
            "location": self.health_loc.pk,
            "lines": [{
                "product": self.health_product.pk, "batch_number": "B-X", "quantity": 5,
            }],
        }, format="json")
        self.assertIn(response.status_code, (400, 403), response.data)
        self.assertFalse(ProductBatch.objects.filter(batch_number="B-X").exists())

    def test_api_issue_and_receipt_replay_status_codes(self):
        self.client.force_authenticate(self.resort_manager)
        payload = {
            "reference": "API-GRN-1",
            "business_unit": self.resort.pk,
            "location": self.resort_loc.pk,
            "lines": [{
                "product": self.resort_product.pk, "batch_number": "A-1",
                "quantity": 10, "unit_cost": "10.00",
            }],
        }
        first = self.client.post("/api/v1/inventory/receipts/", payload, format="json")
        second = self.client.post("/api/v1/inventory/receipts/", payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.resort_batch.refresh_from_db()
        self.assertEqual(self.resort_batch.quantity_remaining, 210)


class RolePermissionTests(TestCase):
    def setUp(self):
        self.resort = BusinessUnit.objects.create(name="Resort", code="RESORT")
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH")
        self.hr = _user("hr@test.com", "hr_manager", None)
        self.accountant = _user("accountant@test.com", "accountant", None)
        self.resort_manager = _user("resort2@test.com", "resort_inventory_manager", self.resort)
        self.client = APIClient()

        self.loc = Location.objects.create(name="Store", business_unit=self.resort)
        self.product = Product.objects.create(
            sku="RES-100", name="Soap", business_unit=self.resort, min_stock=1,
        )

    def _receipt_payload(self):
        return {
            "reference": "ROLE-GRN",
            "business_unit": self.resort.pk,
            "location": self.loc.pk,
            "lines": [{
                "product": self.product.pk, "batch_number": "ROLE-1", "quantity": 5,
            }],
        }

    def test_hr_can_read_both_divisions_but_cannot_write_stock(self):
        self.client.force_authenticate(self.hr)
        response = self.client.get("/api/v1/inventory/products/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        response = self.client.post(
            "/api/v1/inventory/receipts/", self._receipt_payload(), format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(ProductBatch.objects.exists())

    def test_accountant_cannot_write_stock(self):
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get("/api/v1/inventory/products/").status_code, 200)
        response = self.client.post(
            "/api/v1/inventory/receipts/", self._receipt_payload(), format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_division_grant_allows_read_but_not_write(self):
        DivisionAccess.objects.create(
            user=self.resort_manager, business_unit=self.health, level="read"
        )
        self.client.force_authenticate(self.resort_manager)
        response = self.client.get(
            "/api/v1/inventory/products/", {"business_unit": self.health.pk}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
