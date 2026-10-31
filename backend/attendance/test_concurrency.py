from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import User
from .models import AttendanceEvent, OneTimeQRToken, RotatingQRToken
from .tests import BaseQRTest


class ConcurrentQRTests(TransactionTestCase):
    def setUp(self):
        BaseQRTest.setUp(self)

    def race(self, kinds):
        rotating = RotatingQRToken.current_for(self.health, "check_in")
        once = OneTimeQRToken.objects.create(
            token="concurrent-token", employee=self.emp, business_unit=self.health,
            action="check_in", expires_at=timezone.now() + timedelta(minutes=5),
        )
        barrier = Barrier(2)
        user_id = self.emp_user.pk

        def submit(kind):
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=user_id))
                barrier.wait(timeout=10)
                response = client.post(f"/api/v1/attendance/{kind}-qr/verify/", {
                    "token": rotating.token if kind == "rotating" else once.token,
                    "action": "check_in",
                }, format="json")
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, kinds))
        self.assertEqual(results.count(200), 1, results)
        self.assertTrue(all(code in (200, 400, 409, 503) for code in results), results)
        self.assertEqual(AttendanceEvent.objects.filter(employee=self.emp).count(), 1)

    def test_same_one_time_token_concurrently(self):
        self.race(["one-time", "one-time"])

    def test_different_token_types_concurrently(self):
        self.race(["rotating", "one-time"])
