"""
Medicine delivery workflow tests.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import BusinessUnit, Employee, Role, User
from fleet.models import DriverProfile, Vehicle
from inventory.models import Location, Product, ProductBatch
from medicine_delivery.models import DeliveryRequest, DeliveryLineItem

User = get_user_model()


def _token_for(user):
    return str(RefreshToken.for_user(user).access_token)


class MedicineDeliveryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH", is_active=True)
        self.role_inv = Role.objects.create(code="inventory_manager", name="Inventory Manager", business_unit=self.health)
        self.user = User.objects.create_user(
            username="inv@test.com", email="inv@test.com", password="pass123",
            role=self.role_inv, business_unit=self.health, is_active=True, is_approved=True,
        )
        self.emp = Employee.objects.create(
            user=self.user, employee_id="EMP-INV", business_unit=self.health,
            designation="Inventory Manager", is_active=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.user)}")
        self.loc = Location.objects.create(name="Pharmacy", business_unit=self.health, type="storage", is_active=True)
        self.prod = Product.objects.create(
            sku="MED-001", name="Paracetamol", category="Medicine", business_unit=self.health,
            unit="tablet", min_stock=10, is_perishable=False, is_active=True,
        )
        self.batch = ProductBatch.objects.create(
            product=self.prod, batch_number="BATCH-001", quantity_received=100,
            quantity_remaining=100, unit_cost="10.00", status=ProductBatch.STATUS_USABLE,
        )
        self.driver_user = User.objects.create_user(
            username="driver@test.com", email="driver@test.com", password="pass123",
            role=Role.objects.create(code="driver", name="Driver", business_unit=self.health),
            business_unit=self.health, is_active=True, is_approved=True,
        )
        self.driver = DriverProfile.objects.create(
            user=self.driver_user, license_number="DL-1", is_available=True,
        )
        self.vehicle = Vehicle.objects.create(
            license_plate="BA-1001", business_unit=self.health, make="Toyota",
            model="Hiace", capacity=3, status="available",
        )

    def test_full_delivery_workflow(self):
        """Reserve -> dispatch -> deliver reconciles stock."""
        delivery = DeliveryRequest.objects.create(
            reference="DEL-TEST-1", business_unit=self.health,
            recipient_name="Ms. Test", recipient_address="123 Test St",
            status=DeliveryRequest.STATUS_REQUESTED, created_by=self.user,
            assigned_driver=self.driver, assigned_vehicle=self.vehicle,
        )
        DeliveryLineItem.objects.create(
            delivery=delivery, product_batch=self.batch,
            quantity_reserved=10, quantity_delivered=0,
        )

        # reserve
        res = self.client.post(
            f"/api/v1/medicine-delivery/requests/{delivery.id}/reserve/", format="json",
        )
        self.assertEqual(res.status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryRequest.STATUS_RESERVED)

        # dispatch
        res = self.client.post(
            f"/api/v1/medicine-delivery/requests/{delivery.id}/dispatch/", format="json",
        )
        self.assertEqual(res.status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryRequest.STATUS_DISPATCHED)

        # deliver (reconciles stock)
        res = self.client.post(
            f"/api/v1/medicine-delivery/requests/{delivery.id}/deliver/", format="json",
        )
        self.assertEqual(res.status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryRequest.STATUS_DELIVERED)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_remaining, 90)  # 100 - 10 delivered

    def test_cannot_deliver_without_reserve(self):
        delivery = DeliveryRequest.objects.create(
            reference="DEL-TEST-2", business_unit=self.health,
            recipient_name="Ms. Test", recipient_address="123 Test St",
            status=DeliveryRequest.STATUS_REQUESTED, created_by=self.user,
        )
        res = self.client.post(
            f"/api/v1/medicine-delivery/requests/{delivery.id}/deliver/", format="json",
        )
        self.assertEqual(res.status_code, 400)
