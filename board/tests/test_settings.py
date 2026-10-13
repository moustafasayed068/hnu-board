import os
import subprocess
import sys

from django.conf import settings
from django.core.management.utils import get_random_secret_key
from django.test import SimpleTestCase


class ProductionSettingsTests(SimpleTestCase):
    def run_manage(self, *args, **env):
        """Run manage.py in a fresh process, as the server would, with these variables."""
        full_env = {**os.environ, **env}
        return subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=settings.BASE_DIR, env=full_env, capture_output=True, text=True,
        )

    def test_deploy_check_is_clean_and_debug_is_off(self):
        # DJANGO_DEBUG is set to "" (not removed) so a local .env cannot switch it back on.
        # If DEBUG were on, the deploy check would fail with security.W018.
        result = self.run_manage(
            "check", "--deploy", "--fail-level", "WARNING",
            DJANGO_SECRET_KEY=get_random_secret_key(),
            DJANGO_DEBUG="",
            DJANGO_ALLOWED_HOSTS="example.pythonanywhere.com",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no issues", result.stdout)

    def test_only_the_value_1_turns_debug_on(self):
        for value, expected in (("1", "True"), ("true", "False"), ("0", "False")):
            result = self.run_manage(
                "shell", "-c", "from django.conf import settings; print(settings.DEBUG)",
                DJANGO_DEBUG=value,
            )
            self.assertEqual(result.stdout.strip().splitlines()[-1], expected, value)
