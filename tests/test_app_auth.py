import importlib
import os
import tempfile
import unittest

import app_modules.app_auth as app_auth


class AppAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(app_auth)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = app_auth._AUTH_DB_PATH
        self.original_cookie_name = os.environ.get("APP_AUTH_COOKIE_NAME")
        self.original_max_failures = os.environ.get("APP_AUTH_MAX_FAILURES")
        self.original_lockout_seconds = os.environ.get("APP_AUTH_LOCKOUT_SECONDS")
        app_auth._AUTH_DB_PATH = os.path.join(self.temp_dir.name, "auth.sqlite3")

    def tearDown(self) -> None:
        app_auth._AUTH_DB_PATH = self.original_db_path
        if self.original_cookie_name is None:
            os.environ.pop("APP_AUTH_COOKIE_NAME", None)
        else:
            os.environ["APP_AUTH_COOKIE_NAME"] = self.original_cookie_name
        if self.original_max_failures is None:
            os.environ.pop("APP_AUTH_MAX_FAILURES", None)
        else:
            os.environ["APP_AUTH_MAX_FAILURES"] = self.original_max_failures
        if self.original_lockout_seconds is None:
            os.environ.pop("APP_AUTH_LOCKOUT_SECONDS", None)
        else:
            os.environ["APP_AUTH_LOCKOUT_SECONDS"] = self.original_lockout_seconds
        self.temp_dir.cleanup()

    def test_create_validate_and_revoke_auth_token(self) -> None:
        now = 1_700_000_000.0
        token, ttl = app_auth._create_auth_token("alice", now, remember=False)
        self.assertGreater(ttl, 0)

        validated = app_auth._validate_auth_token(token, "alice", now + 5)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["username"], "alice")

        app_auth._revoke_auth_token(token)
        self.assertIsNone(app_auth._validate_auth_token(token, "alice", now + 5))

    def test_auth_cookie_name_uses_namespaced_override(self) -> None:
        os.environ["APP_AUTH_COOKIE_NAME"] = "service-01.auth"
        self.assertEqual(app_auth._auth_cookie_name(), "service-01auth")

    def test_failed_attempts_persist_and_trigger_lockout(self) -> None:
        os.environ["APP_AUTH_MAX_FAILURES"] = "2"
        os.environ["APP_AUTH_LOCKOUT_SECONDS"] = "120"
        now = 1_700_000_000.0

        self.assertEqual(app_auth._register_failed_attempt(now), 0)
        self.assertEqual(app_auth._remaining_lockout_seconds(now), 0)

        lockout_seconds = app_auth._register_failed_attempt(now + 1)
        self.assertEqual(lockout_seconds, 120)
        self.assertEqual(app_auth._remaining_lockout_seconds(now + 1), 120)

        # Reload module to emulate a separate worker/process initialization.
        db_path = app_auth._AUTH_DB_PATH
        importlib.reload(app_auth)
        app_auth._AUTH_DB_PATH = db_path

        self.assertEqual(app_auth._remaining_lockout_seconds(now + 2), 119)


if __name__ == "__main__":
    unittest.main()
