import importlib
import os
import sys
import tempfile
import types
import unittest


streamlit_module = types.ModuleType("streamlit")
streamlit_module.session_state = {}
streamlit_module.context = types.SimpleNamespace(cookies={})


def _cache_resource(show_spinner: bool = False):
    def _decorator(fn):
        return fn

    return _decorator


streamlit_module.cache_resource = _cache_resource
streamlit_module.sidebar = types.SimpleNamespace(__enter__=lambda self: self, __exit__=lambda self, exc_type, exc, tb: False)
streamlit_module.caption = lambda *args, **kwargs: None
streamlit_module.button = lambda *args, **kwargs: False
streamlit_module.error = lambda *args, **kwargs: None
streamlit_module.warning = lambda *args, **kwargs: None
streamlit_module.title = lambda *args, **kwargs: None
streamlit_module.markdown = lambda *args, **kwargs: None
streamlit_module.stop = lambda: None
streamlit_module.form = lambda *args, **kwargs: None
streamlit_module.text_input = lambda *args, **kwargs: ""
streamlit_module.checkbox = lambda *args, **kwargs: False
streamlit_module.form_submit_button = lambda *args, **kwargs: False
streamlit_module.rerun = lambda: None

components_module = types.ModuleType("streamlit.components")
components_v1_module = types.ModuleType("streamlit.components.v1")
components_v1_module.html = lambda *args, **kwargs: None

sys.modules.setdefault("streamlit", streamlit_module)
sys.modules.setdefault("streamlit.components", components_module)
sys.modules.setdefault("streamlit.components.v1", components_v1_module)

import app_modules.app_auth as app_auth


class AppAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = app_auth._AUTH_DB_PATH
        self.original_cookie_name = os.environ.get("APP_AUTH_COOKIE_NAME")
        app_auth._AUTH_DB_PATH = os.path.join(self.temp_dir.name, "auth.sqlite3")
        streamlit_module.session_state.clear()
        streamlit_module.context.cookies = {}
        importlib.reload(app_auth)
        app_auth._AUTH_DB_PATH = os.path.join(self.temp_dir.name, "auth.sqlite3")

    def tearDown(self) -> None:
        app_auth._AUTH_DB_PATH = self.original_db_path
        if self.original_cookie_name is None:
            os.environ.pop("APP_AUTH_COOKIE_NAME", None)
        else:
            os.environ["APP_AUTH_COOKIE_NAME"] = self.original_cookie_name
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


if __name__ == "__main__":
    unittest.main()
