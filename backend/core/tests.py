from datetime import timedelta
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import Role, User


class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.role = Role.objects.create(code="super_admin", name="Super Admin")
        self.user = User.objects.create_user(username="admin", email="admin@test.com",
            password="Test-password-123", role=self.role, is_approved=True)

    def login(self):
        return self.client.post("/api/v1/auth/login/", {
            "email": self.user.email, "password": "Test-password-123"}, format="json")

    def test_login_restore_refresh_logout(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        tokens = response.data
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens["access"])
        self.assertEqual(self.client.get("/api/v1/auth/me/").data["id"], self.user.pk)
        refresh = self.client.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}).status_code, 401)

    def test_invalid_credentials_and_anonymous_access(self):
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/login/", {"email": self.user.email, "password": "wrong"}).status_code, 401)

    def test_expired_tokens_and_stale_header_login(self):
        token = RefreshToken.for_user(self.user)
        access = token.access_token
        access.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + str(access))
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.assertEqual(self.client.post("/api/v1/auth/refresh/", {"refresh": str(token)}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/logout/", {"refresh": "invalid"}).status_code, 200)

    def test_revoked_approval_disabled_deleted_refresh(self):
        token = str(RefreshToken.for_user(self.user))
        self.user.is_approved = False
        self.user.save()
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/refresh/", {"refresh": token}).status_code, 401)
        self.user.is_approved = True
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.post("/api/v1/auth/refresh/", {"refresh": token}).status_code, 401)
        self.user.delete()
        self.assertEqual(self.client.post("/api/v1/auth/refresh/", {"refresh": token}).status_code, 401)

    def test_role_escalation_denied(self):
        for code in ["hr_manager", "resort_inventory_manager", "healthcare_inventory_manager"]:
            with self.subTest(role=code):
                role = Role.objects.create(code=code, name=code)
                self.user.role = role
                self.user.save()
                self.client.force_authenticate(self.user)
                response = self.client.patch(f"/api/v1/users/{self.user.pk}/", {"role": self.role.pk}, format="json")
                self.assertEqual(response.status_code, 403)

    def test_super_admin_can_manage_unassigned_account(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.login().data["access"])
        response = self.client.patch(f"/api/v1/users/{self.user.pk}/", {"first_name": "Admin"}, format="json")
        self.assertEqual(response.status_code, 200)

    @override_settings(CORS_ALLOW_ALL_ORIGINS=False, CORS_ALLOWED_ORIGINS=[
        "http://localhost:3000", "https://homs-test.vercel.app"])
    def test_deployment_origin_matrix(self):
        # Reserved test hostnames; no live infrastructure is contacted.
        for origin, host in [("http://localhost:3000", "localhost"),
                             ("http://localhost:3000", "testserver"),
                             ("https://homs-test.vercel.app", "testserver")]:
            with self.subTest(origin=origin, host=host):
                response = self.client.options("/api/v1/auth/login/", HTTP_ORIGIN=origin,
                    HTTP_HOST=host, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                    HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type")
                self.assertEqual(response["access-control-allow-origin"], origin)
                response = self.client.post("/api/v1/auth/login/", {
                    "email": self.user.email, "password": "Test-password-123"}, HTTP_ORIGIN=origin, HTTP_HOST=host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["access-control-allow-origin"], origin)
        response = self.client.options("/api/v1/auth/login/", HTTP_ORIGIN="https://untrusted.vercel.app",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("access-control-allow-origin", response)

    def test_session_authentication_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/api/v1/roles/", {"name": "Role", "code": "role"}).status_code, 403)
