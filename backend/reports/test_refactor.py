from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from core.models import BusinessUnit, Role, User, Employee
from attendance.models import AttendanceEvent, RotatingQRToken
from fleet.models import Vehicle, DriverProfile
from nemt.models import TransportRequest, Trip


class PageRegressionTests(TestCase):
    def setUp(self):
        self.unit = BusinessUnit.objects.create(name="Test workplace", code="QA")
        self.other = BusinessUnit.objects.create(name="Other workplace", code="OTHER")
        self.role = Role.objects.create(name="Employee", code="employee")
        self.user = User.objects.create_user(username="page", email="page@example.test", password="test-pass", business_unit=self.unit, role=self.role)
        self.employee = Employee.objects.create(user=self.user, business_unit=self.unit, employee_id="PAGE-1")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_dashboard_real_counts_and_scope(self):
        Vehicle.objects.create(license_plate="QA-1", business_unit=self.unit, status="available")
        Vehicle.objects.create(license_plate="OTHER", business_unit=self.other, status="available")
        for action in ["check_in", "check_out", "check_in"]:
            AttendanceEvent.objects.create(employee=self.employee, business_unit=self.unit, action=action, timestamp=timezone.now())
        TransportRequest.objects.create(reference="QAR", business_unit=self.unit, patient_name="QA", pickup_location="A", dropoff_location="B", pickup_time=timezone.now())
        data = self.client.get("/api/v1/reports/dashboard/").data
        self.assertEqual((data["employees"], data["checked_in_today"], data["active_vehicles"], data["pending_requests"]), (1, 1, 1, 1))
        self.assertEqual(data["weekly"][-1]["checkins"], 2)
        self.assertEqual(len(data["weekly"]), 7)
        self.assertEqual(len(data["recent"]), 3)

    def test_five_users_can_scan_same_qr_once_each(self):
        qr = RotatingQRToken.current_for(self.unit, "check_in")
        for i in range(5):
            user = User.objects.create_user(username=f"scan{i}", email=f"scan{i}@example.test", business_unit=self.unit, role=self.role)
            employee = Employee.objects.create(user=user, business_unit=self.unit, employee_id=f"SCAN-{i}")
            self.client.force_authenticate(user)
            endpoint = "/api/v1/attendance/rotating-qr/verify/"
            response = self.client.post(endpoint, {"token": qr.token, "action": "check_in"}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["event"]["employee"], employee.pk)
            self.assertEqual(self.client.post(endpoint, {"token": qr.token, "action": "check_in"}, format="json").status_code, 409)
        self.assertEqual(AttendanceEvent.objects.count(), 5)

    def test_trip_uses_trip_id_and_updates_request(self):
        driver = DriverProfile.objects.create(user=self.user, license_number="QA-D")
        vehicle = Vehicle.objects.create(license_plate="QA-V", business_unit=self.unit)
        req = TransportRequest.objects.create(reference="QA-TRIP", business_unit=self.unit, patient_name="QA", pickup_location="A", dropoff_location="B", pickup_time=timezone.now())
        response = self.client.post("/api/v1/nemt/trips/", {"request": req.id, "driver": driver.id, "vehicle": vehicle.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        req.refresh_from_db()
        self.assertEqual(req.status, "assigned")
        for status in ["started", "picked_up", "dropoffed", "completed"]:
            response = self.client.post(f"/api/v1/nemt/trips/{response.data['id']}/transition/", {"status": status}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
        req.refresh_from_db()
        self.assertEqual(req.status, "completed")

    def test_health_is_public_but_dashboard_requires_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/v1/health/").json(), {"service": "homs", "version": 1})
        self.assertEqual(self.client.get("/api/v1/reports/dashboard/").status_code, 401)
