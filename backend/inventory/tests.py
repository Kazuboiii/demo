"""
Inventory data-integrity tests.

- Prevent negative usable stock.
- Block issuing expired or quarantined stock.
- Auditable stock movement history.
"""

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import BusinessUnit, Department, Employee, Role, User
from inventory.models import Location, Product, ProductBatch, StockIssue, StockIssueLine


def _token_for(user):
    return str(RefreshToken.for_user(user).access_token)


class InventoryIntegrityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH", is_active=True)
        self.role_inv = Role.objects.create(code="inventory_manager", name="Inventory Manager", business_unit=self.health)
        self.user = User.objects.create_user(
            username="inv@test.com", email="inv@test.com", password="pass123",
            role=self.role_inv, business_unit=self.health, is_active=True, is_approved=True,
        )
        self.emp = Employee.objects.create(
            user=self.user, employee_id="EMP-INV", business_unit=self.health, designation="Inventory Manager", is_active=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.user)}")
        self.dept = Department.objects.create(name="Pharmacy Dept", business_unit=self.health, is_active=True)
        self.loc = Location.objects.create(name="Pharmacy", business_unit=self.health, type="storage", is_active=True)
        self.prod = Product.objects.create(
            sku="MED-001", name="Paracetamol", category="Medicine", business_unit=self.health,
            unit="tablet", min_stock=10, is_perishable=False, is_active=True,
        )
        today = timezone.now().date()
        self.batch = ProductBatch.objects.create(
            product=self.prod, batch_number="BATCH-001", expiry_date=today + timedelta(days=365),
            quantity_received=100, quantity_remaining=100, unit_cost="10.00", status=ProductBatch.STATUS_USABLE,
        )
        self.expired_batch = ProductBatch.objects.create(
            product=self.prod, batch_number="BATCH-EXP", expiry_date=today - timedelta(days=10),
            quantity_received=10, quantity_remaining=10, unit_cost="10.00", status=ProductBatch.STATUS_USABLE,
        )
        self.quarantined_batch = ProductBatch.objects.create(
            product=self.prod, batch_number="BATCH-Q", expiry_date=today + timedelta(days=365),
            quantity_received=10, quantity_remaining=10, unit_cost="10.00", status=ProductBatch.STATUS_QUARANTINED,
        )

    def _post_issue(self, lines):
        return self.client.post(
            "/api/v1/inventory/issues/",
            {
                "reference": f"ISSUE-{self.batch.id}-{self.prod.id}",
                "business_unit": self.health.id,
                "department": self.dept.id,
                "lines": lines,
            },
            format="json",
        )

    def test_usable_stock_cannot_go_negative(self):
        """Prevent negative usable stock."""
        res = self._post_issue([
            {"product_batch": self.batch.id, "quantity": 150},
        ])
        self.assertEqual(res.status_code, 400)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_remaining, 100)

    def test_valid_stock_issue_reduces_stock(self):
        """Valid stock issue deducts quantity and records movement."""
        res = self._post_issue([
            {"product_batch": self.batch.id, "quantity": 30},
        ])
        self.assertEqual(res.status_code, 201)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_remaining, 70)
        self.assertTrue(
            self.batch.movements.filter(movement_type="issue").exists()
        )

    def test_expired_stock_issuance_blocked(self):
        """Expired stock must not be issued."""
        res = self._post_issue([
            {"product_batch": self.expired_batch.id, "quantity": 5},
        ])
        self.assertEqual(res.status_code, 400)
        self.expired_batch.refresh_from_db()
        self.assertEqual(self.expired_batch.quantity_remaining, 10)

    def test_quarantined_stock_issuance_blocked(self):
        """Quarantined stock must not be issued."""
        res = self._post_issue([
            {"product_batch": self.quarantined_batch.id, "quantity": 5},
        ])
        self.assertEqual(res.status_code, 400)
        self.quarantined_batch.refresh_from_db()
        self.assertEqual(self.quarantined_batch.quantity_remaining, 10)


class BarcodeAndLabelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH", is_active=True)
        self.role_inv = Role.objects.create(code="inventory_manager", name="Inventory Manager", business_unit=self.health)
        self.user = User.objects.create_user(
            username="inv2@test.com", email="inv2@test.com", password="pass123",
            role=self.role_inv, business_unit=self.health, is_active=True, is_approved=True,
        )
        self.emp = Employee.objects.create(
            user=self.user, employee_id="EMP-INV2", business_unit=self.health,
            designation="Inventory Manager", is_active=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.user)}")
        self.loc = Location.objects.create(name="Pharmacy", business_unit=self.health, type="storage", is_active=True)
        self.prod = Product.objects.create(
            sku="MED-001", barcode="8901234567890", name="Paracetamol", category="Medicine",
            business_unit=self.health, unit="tablet", min_stock=10,
            is_perishable=False, batch_tracking_required=True, is_active=True,
        )
        today = timezone.now().date()
        self.batch = ProductBatch.objects.create(
            product=self.prod, batch_number="BATCH-001", expiry_date=today + timedelta(days=365),
            quantity_received=100, quantity_remaining=100, unit_cost="10.00",
            status=ProductBatch.STATUS_USABLE,
        )

    def test_barcode_lookup_found(self):
        res = self.client.get(
            f"/api/v1/inventory/products/lookup/?barcode={self.prod.barcode}&business_unit={self.health.id}",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["sku"], self.prod.sku)
        self.assertEqual(res.data["barcode"], self.prod.barcode)

    def test_barcode_lookup_not_found(self):
        res = self.client.get("/api/v1/inventory/products/lookup/?barcode=0000000000000")
        self.assertEqual(res.status_code, 404)

    def test_barcode_lookup_missing_param(self):
        res = self.client.get("/api/v1/inventory/products/lookup/")
        self.assertEqual(res.status_code, 400)

    def test_batch_label_json(self):
        res = self.client.get(f"/api/v1/inventory/batches/{self.batch.id}/label/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["lot_id"], self.batch.id)
        self.assertEqual(res.data["product_name"], self.prod.name)
        self.assertEqual(res.data["sku"], self.prod.sku)
        self.assertEqual(res.data["batch_number"], self.batch.batch_number)

    def test_batch_qr_label_png(self):
        res = self.client.get(f"/api/v1/inventory/batches/{self.batch.id}/qr_label/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "image/png")
        self.assertTrue(res.content.startswith(b"\x89PNG"))
