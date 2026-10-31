from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from .tests import BaseQRTest
from .models import AttendanceEvent, OneTimeQRToken, RotatingQRToken


class QRRegressionTests(BaseQRTest):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.emp_user)

    def token(self, action="check_in"):
        return OneTimeQRToken.objects.create(
            token=f"one-time-{action}", employee=self.emp, business_unit=self.health,
            action=action, expires_at=timezone.now() + timedelta(minutes=5),
        )

    def verify(self, token, action="check_in", kind="one-time"):
        return self.client.post(f"/api/v1/attendance/{kind}-qr/verify/",
                                {"token": token, "action": action}, format="json")

    def test_explicit_discriminator_only_for_owned_one_time_token(self):
        qr = self.token()
        self.assertEqual(self.verify(qr.token, kind="rotating").data["code"], "one_time_token")
        self.assertEqual(self.verify("unknown", kind="rotating").data["code"], "invalid_token")
        self.client.force_authenticate(self.emp2_user)
        self.assertEqual(self.verify(qr.token, kind="rotating").data["code"], "invalid_token")

    def test_action_mismatch_does_not_consume_token(self):
        qr = self.token()
        self.assertEqual(self.verify(qr.token, "check_out").status_code, 400)
        qr.refresh_from_db()
        self.assertEqual(qr.status, "active")
        self.assertEqual(AttendanceEvent.objects.count(), 0)

    def test_check_out_requires_check_in_and_cannot_repeat(self):
        qr_in, qr_out = self.token(), self.token("check_out")
        self.assertEqual(self.verify(qr_out.token, "check_out").status_code, 400)
        self.assertEqual(self.verify(qr_in.token).status_code, 200)
        result = self.verify(qr_out.token, "check_out")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["event"]["action"], "check_out")
        self.assertEqual(self.verify(qr_out.token, "check_out").status_code, 400)
        self.assertEqual(AttendanceEvent.objects.count(), 2)

    def test_stale_model_cannot_redeem_used_token_after_checkout(self):
        qr = self.token()
        stale = OneTimeQRToken.objects.get(pk=qr.pk)
        self.assertTrue(qr.redeem(self.emp)[0])
        self.assertTrue(self.token("check_out").redeem(self.emp)[0])
        self.assertFalse(stale.redeem(self.emp)[0])
        self.assertEqual(AttendanceEvent.objects.count(), 2)

    def test_event_failure_rolls_back_token_consumption(self):
        qr = self.token()
        with patch("attendance.models.AttendanceEvent.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                qr.redeem(self.emp)
        qr.refresh_from_db()
        self.assertEqual(qr.status, "active")

    def test_expiration_boundary(self):
        qr = self.token()
        self.assertFalse(qr.is_valid_for(self.emp, now=qr.expires_at)[0])
        rotating = RotatingQRToken.current_for(self.health, "check_in")
        self.assertTrue(rotating.is_expired(now=rotating.expires_at))

    def test_bad_payloads_and_unapproved_user(self):
        for kind in ("rotating", "one-time"):
            for token, action in (("", "check_in"), ({}, "check_in"), ("x", "invalid")):
                self.assertEqual(self.verify(token, action, kind).status_code, 400)
        self.emp_user.is_approved = False
        self.emp_user.save()
        self.assertEqual(self.verify(self.token().token).status_code, 403)

    def test_staff_cannot_list_other_tokens_or_revoke(self):
        qr = self.token()
        self.client.force_authenticate(self.emp2_user)
        result = self.client.get("/api/v1/attendance/one-time-qr/")
        self.assertEqual(result.data["results"], [])
        self.assertEqual(self.client.post(f"/api/v1/attendance/one-time-qr/{qr.pk}/revoke/").status_code, 403)

    def test_rotating_checkout_without_checkin_rejected(self):
        qr = RotatingQRToken.current_for(self.health, "check_out")
        self.assertEqual(self.verify(qr.token, "check_out", "rotating").status_code, 409)

    def test_auth_me_requires_authentication(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)
