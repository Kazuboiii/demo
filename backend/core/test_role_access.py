from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from core.models import User
from core.role_access import ROLE_CHOICES


@override_settings(ROLE_LOGIN=True)
class RoleAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_every_role_provisions_and_authenticates_without_password(self):
        for code, _, unit in ROLE_CHOICES:
            with self.subTest(role=code):
                response = self.client.post("/api/v1/auth/role-login/", {"role": code})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["user"]["role_code"], code)
                self.assertEqual(response.data["user"]["business_unit_code"], unit)
                user = User.objects.get(pk=response.data["user"]["id"])
                self.assertFalse(user.has_usable_password())
                self.client.credentials(HTTP_AUTHORIZATION="Bearer " + response.data["access"])
                self.assertEqual(self.client.get("/api/v1/auth/workspace/").status_code, 200)
                self.client.credentials()
                repeated = self.client.post("/api/v1/auth/role-login/", {"role": code})
                self.assertEqual(repeated.data["user"]["id"], user.pk)
        self.assertEqual(User.objects.count(), len(ROLE_CHOICES))

    def test_listing_does_not_create_accounts_and_rejects_unknown_roles(self):
        self.assertEqual(len(self.client.get("/api/v1/auth/role-login/").data), 6)
        for role in ("unknown", ["super_admin"], None):
            self.assertEqual(self.client.post("/api/v1/auth/role-login/", {"role": role}, format="json").status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_disabled_account_is_not_reenabled(self):
        response = self.client.post("/api/v1/auth/role-login/", {"role": "employee"})
        User.objects.filter(pk=response.data["user"]["id"]).update(is_active=False)
        self.assertEqual(self.client.post("/api/v1/auth/role-login/", {"role": "employee"}).status_code, 403)

    @override_settings(ROLE_LOGIN=False)
    def test_disabled_feature(self):
        self.assertEqual(self.client.get("/api/v1/auth/role-login/").status_code, 404)
        self.assertEqual(self.client.post("/api/v1/auth/role-login/", {"role": "super_admin"}).status_code, 404)
