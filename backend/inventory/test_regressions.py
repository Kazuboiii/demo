from unittest.mock import patch

from .tests import InventoryIntegrityTests
from .models import StockReceipt, StockMovement, StockIssue


class InventoryRegressionTests(InventoryIntegrityTests):
    def receipt(self):
        return self.client.post("/api/v1/inventory/receipts/", {
            "reference": "receipt-regression", "business_unit": self.health.pk,
            "location": self.loc.pk,
            "lines": [{"product": self.prod.pk, "batch_number": "NEW", "quantity": 3,
                       "unit_cost": "1.00"}],
        }, format="json")

    def test_receipt_records_parent_location(self):
        result = self.receipt()
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(StockMovement.objects.get(reference="receipt-regression").location, self.loc)
        self.assertEqual(self.prod.batches.get(batch_number="NEW").quantity_remaining, 3)

    def test_receipt_failure_rolls_back_everything(self):
        with patch("inventory.models.StockMovement.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.receipt()
        self.assertFalse(StockReceipt.objects.exists())
        self.assertFalse(self.prod.batches.filter(batch_number="NEW").exists())

    def test_failed_issue_does_not_leave_header(self):
        result = self._post_issue([{"product_batch": self.batch.pk, "quantity": 1000}])
        self.assertEqual(result.status_code, 400)
        self.assertFalse(StockIssue.objects.exists())

    def test_usable_stock_excludes_expired_batches(self):
        self.assertEqual(self.prod.usable_stock(), 100)
