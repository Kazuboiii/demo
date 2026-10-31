"""
Backend tests for the QR attendance module.

Covers both rotating (shared workplace) QR and one-time (employee-specific)
QR modes, including expiry, duplicate prevention, authorization, and
concurrent redemption safety.
"""

from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import BusinessUnit, Employee, Role
from attendance.models import (
    AttendanceEvent,
    RotatingQRToken,
    RotatingQRRedemption,
    OneTimeQRToken,
    Shift,
)

User = get_user_model()


def _token_for(user):
    return str(RefreshToken.for_user(user).access_token)


class BaseQRTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.health = BusinessUnit.objects.create(name="Healthcare", code="HEALTH", is_active=True)
        self.resort = BusinessUnit.objects.create(name="Resort", code="RESORT", is_active=True)
        self.role_hr = Role.objects.create(code="hr_manager", name="HR Manager", business_unit=self.health)
        self.role_emp = Role.objects.create(code="employee", name="Employee", business_unit=self.health)
        self.role_driver = Role.objects.create(code="driver", name="Driver", business_unit=self.health)
        self.role_super = Role.objects.create(code="super_admin", name="Super Administrator")

        self.hr_user = User.objects.create_user(
            username="hr@test.com", email="hr@test.com", password="pass123", first_name="HR", last_name="User",
            role=self.role_hr, business_unit=self.health, is_active=True, is_approved=True,
        )
        self.hr_emp = Employee.objects.create(
            user=self.hr_user, employee_id="EMP-HR", business_unit=self.health,
            designation="HR Manager", is_active=True,
        )

        self.emp_user = User.objects.create_user(
            username="emp@test.com", email="emp@test.com", password="pass123", first_name="Emp", last_name="One",
            role=self.role_emp, business_unit=self.health, is_active=True, is_approved=True,
        )
        self.emp = Employee.objects.create(
            user=self.emp_user, employee_id="EMP-001", business_unit=self.health,
            designation="Staff", is_active=True,
        )

        self.emp2_user = User.objects.create_user(
            username="emp2@test.com", email="emp2@test.com", password="pass123", first_name="Emp", last_name="Two",
            role=self.role_emp, business_unit=self.health, is_active=True, is_approved=True,
        )
        self.emp2 = Employee.objects.create(
            user=self.emp2_user, employee_id="EMP-002", business_unit=self.health,
            designation="Staff", is_active=True,
        )

        self.driver_user = User.objects.create_user(
            username="driver@test.com", email="driver@test.com", password="pass123", first_name="Drv", last_name="One",
            role=self.role_driver, business_unit=self.health, is_active=True, is_approved=True,
        )
        self.driver = Employee.objects.create(
            user=self.driver_user, employee_id="EMP-DRV", business_unit=self.health,
            designation="Driver", is_active=True,
        )

        self.shift = Shift.objects.create(
            name="Day", business_unit=self.health, start_time="08:00", end_time="16:00",
            overnight=False, grace_minutes=15, is_active=True,
        )


class RotatingQRTests(BaseQRTest):
    def test_valid_rotating_qr_accepted(self):
        """Scenario 1: Valid rotating QR accepted."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        now = timezone.now()
        qr = RotatingQRToken.objects.create(
            business_unit=self.health, action="check_in",
            token="valid-rotating-token", issued_at=now,
            expires_at=now + timedelta(seconds=30), is_active=True,
        )
        res = self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(AttendanceEvent.objects.filter(employee=self.emp, action="check_in").exists())
        self.assertTrue(RotatingQRRedemption.objects.filter(token=qr, employee=self.emp).exists())

    def test_expired_rotating_qr_rejected(self):
        """Scenario 2: Expired rotating QR rejected."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        now = timezone.now()
        qr = RotatingQRToken.objects.create(
            business_unit=self.health, action="check_in",
            token="expired-rotating-token", issued_at=now - timedelta(seconds=60),
            expires_at=now - timedelta(seconds=30), is_active=True,
        )
        res = self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 410)

    def test_duplicate_employee_checkin_rejected(self):
        """Scenario 3: Duplicate employee check-in rejected (same QR, same employee)."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        now = timezone.now()
        qr = RotatingQRToken.objects.create(
            business_unit=self.health, action="check_in",
            token="dup-rotating-token", issued_at=now,
            expires_at=now + timedelta(seconds=30), is_active=True,
        )
        # First redemption
        self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        # Second redemption by same employee - should be rejected
        res = self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(RotatingQRRedemption.objects.filter(token=qr, employee=self.emp).count(), 1)

    def test_shared_rotating_qr_two_employees(self):
        """Scenario 4: Shared rotating QR works for two different eligible employees."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        now = timezone.now()
        qr = RotatingQRToken.objects.create(
            business_unit=self.health, action="check_in",
            token="shared-rotating-token", issued_at=now,
            expires_at=now + timedelta(seconds=30), is_active=True,
        )
        # Emp 1 redeems
        self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        # Emp 2 redeems same token (shared workplace QR)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp2_user)}")
        res = self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(RotatingQRRedemption.objects.filter(token=qr).count(), 2)

    def test_checkin_then_checkout_allowed(self):
        """An employee can check out after checking in (different action)."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        now = timezone.now()
        qr_in = RotatingQRToken.objects.create(
            business_unit=self.health, action="check_in", token="in-token",
            issued_at=now, expires_at=now + timedelta(seconds=30), is_active=True,
        )
        qr_out = RotatingQRToken.objects.create(
            business_unit=self.health, action="check_out", token="out-token",
            issued_at=now, expires_at=now + timedelta(seconds=30), is_active=True,
        )
        self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr_in.token, "action": "check_in"}, format="json")
        res = self.client.post("/api/v1/attendance/rotating-qr/verify/", {"token": qr_out.token, "action": "check_out"}, format="json")
        self.assertEqual(res.status_code, 200)


class OneTimeQRTests(BaseQRTest):
    def _generate_ot(self, employee, action="check_in", minutes=5, issued_by=None):
        now = timezone.now()
        return OneTimeQRToken.objects.create(
            employee=employee, business_unit=self.health, action=action,
            issued_by=issued_by or self.hr_user,
            token=f"ot-{employee.employee_id}-{action}",
            expires_at=now + timedelta(minutes=minutes),
            status=OneTimeQRToken.STATUS_ACTIVE,
        )

    def test_one_time_qr_accepted_once(self):
        """Scenario 5: One-time QR accepted once."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        qr = self._generate_ot(self.emp)
        res = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 200)
        qr.refresh_from_db()
        self.assertEqual(qr.status, OneTimeQRToken.STATUS_USED)
        self.assertTrue(AttendanceEvent.objects.filter(employee=self.emp, action="check_in").exists())

    def test_one_time_qr_reuse_rejected(self):
        """Scenario 6: One-time QR reuse rejected."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        qr = self._generate_ot(self.emp)
        self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        res = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(AttendanceEvent.objects.filter(employee=self.emp, action="check_in").count(), 1)

    def test_one_time_qr_wrong_employee_rejected(self):
        """Scenario 7: One-time QR rejected for wrong employee."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp2_user)}")
        qr = self._generate_ot(self.emp)  # issued for emp, scanned by emp2
        res = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_one_time_qr_wrong_workplace_rejected(self):
        """Scenario 8: One-time QR rejected for wrong workplace."""
        # Create an employee in the resort unit
        resort_emp_user = User.objects.create_user(
            username="resort@test.com", email="resort@test.com", password="pass123", first_name="Resort", last_name="Emp",
            role=self.role_emp, business_unit=self.resort, is_active=True, is_approved=True,
        )
        resort_emp = Employee.objects.create(
            user=resort_emp_user, employee_id="EMP-R1", business_unit=self.resort,
            designation="Staff", is_active=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(resort_emp_user)}")
        qr = self._generate_ot(resort_emp)  # belongs to resort
        # Now have a health employee try it
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        # Make a resort-scoped token but health employee scans
        qr2 = OneTimeQRToken.objects.create(
            employee=resort_emp, business_unit=self.resort, action="check_in",
            issued_by=self.hr_user, token="ot-resort-wrong",
            expires_at=timezone.now() + timedelta(minutes=5),
            status=OneTimeQRToken.STATUS_ACTIVE,
        )
        res = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr2.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_one_time_qr_expired_rejected(self):
        """Scenario 9: One-time QR rejected after expiry."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        now = timezone.now()
        qr = OneTimeQRToken.objects.create(
            employee=self.emp, business_unit=self.health, action="check_in",
            issued_by=self.hr_user, token="ot-expired-token",
            expires_at=now - timedelta(minutes=1),
            status=OneTimeQRToken.STATUS_ACTIVE,
        )
        res = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_revoked_qr_rejected(self):
        """Scenario 10: Revoked QR rejected."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        qr = self._generate_ot(self.emp)
        qr.status = OneTimeQRToken.STATUS_REVOKED
        qr.save(update_fields=["status"])
        res = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_unauthorized_qr_generation_rejected(self):
        """Scenario 11: Unauthorized QR generation rejected."""
        # A regular employee (not HR) tries to generate one-time QR via the API list/create
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        res = self.client.post(
            "/api/v1/attendance/one-time-qr/",
            {"employee": self.emp.id, "action": "check_in", "validity_minutes": 5},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_concurrent_one_time_redemption_no_duplicate(self):
        """Scenario 12: Concurrent one-time redemption does not create duplicate attendance events."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(self.emp_user)}")
        qr = self._generate_ot(self.emp)
        # Submit two concurrent-ish requests
        res1 = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        res2 = self.client.post("/api/v1/attendance/one-time-qr/verify/", {"token": qr.token, "action": "check_in"}, format="json")
        statuses = sorted([res1.status_code, res2.status_code])
        self.assertEqual(statuses, [200, 400])
        self.assertEqual(AttendanceEvent.objects.filter(employee=self.emp, action="check_in").count(), 1)
