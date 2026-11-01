from io import StringIO
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from attendance.models import AttendanceEvent
from core.models import Employee
from inventory.models import ProductBatch, StockMovement


@override_settings(ROLE_LOGIN=True)
class WorkspaceSamplesTests(TestCase):
    def test_samples_repeat_without_duplicate_attendance_or_stock(self):
        call_command("seed_workspace", stdout=StringIO())
        balances = list(ProductBatch.objects.order_by("pk").values_list("quantity_remaining", flat=True))
        call_command("seed_workspace", stdout=StringIO())
        self.assertEqual(Employee.objects.count(), 6)
        self.assertEqual(AttendanceEvent.objects.count(), 60)
        self.assertEqual(StockMovement.objects.count(), 6)
        self.assertEqual(list(ProductBatch.objects.order_by("pk").values_list("quantity_remaining", flat=True)), balances)
        for batch in ProductBatch.objects.all():
            self.assertEqual(batch.quantity_remaining, sum(StockMovement.objects.filter(product_batch=batch).values_list("quantity", flat=True)))

    def test_phone_role_can_check_in_out_and_read_history(self):
        client = APIClient()
        login = client.post("/api/v1/auth/role-login/", {"role": "employee"})
        self.assertEqual(login.status_code, 200)
        client.credentials(HTTP_AUTHORIZATION="Bearer " + login.data["access"])
        for action in ("check_in", "check_out"):
            qr = client.get("/api/v1/attendance/rotating-qr/", {"action": action})
            self.assertEqual(qr.status_code, 200)
            response = client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.data["token"], "action": action})
            self.assertEqual(response.status_code, 200)
            duplicate = client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.data["token"], "action": action})
            self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(client.get("/api/v1/attendance/events/mine/").status_code, 200)
        self.assertEqual(AttendanceEvent.objects.count(), 2)
