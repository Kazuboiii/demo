"""Production settings checks without connecting to a database."""
import os
import subprocess
import sys
from pathlib import Path
from django.test import SimpleTestCase


class RenderSettingsTests(SimpleTestCase):
    def settings_process(self, database_url):
        env = {**os.environ,
               "DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "test-only-key-not-a-production-secret-123456789",
               "DJANGO_ALLOWED_HOSTS": "", "RENDER": "true",
               "RENDER_EXTERNAL_HOSTNAME": "demo-jpuo.onrender.com",
               "DATABASE_URL": database_url}
        return subprocess.run([sys.executable, "-c",
            "from uems_config.settings import ALLOWED_HOSTS; assert 'demo-jpuo.onrender.com' in ALLOWED_HOSTS"],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True)

    def test_render_hostname_is_allowed(self):
        result = self.settings_process("sqlite:///:memory:")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_render_does_not_silently_create_empty_sqlite_identity_store(self):
        result = self.settings_process("")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL must point to the existing persistent database", result.stderr)
