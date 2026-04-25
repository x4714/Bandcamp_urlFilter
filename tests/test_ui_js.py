import importlib
import sys
import types
import unittest


streamlit_module = types.ModuleType("streamlit")
iframe_calls: list[tuple[str, int]] = []
html_calls: list[tuple[str, int, int]] = []


def _iframe(body: str, *, height: int = 0):
    iframe_calls.append((body, height))


def _html(body: str, *, height: int = 0, width: int = 0):
    html_calls.append((body, height, width))


streamlit_module.iframe = _iframe
components_module = types.ModuleType("streamlit.components")
components_v1_module = types.ModuleType("streamlit.components.v1")
components_v1_module.html = _html

sys.modules.setdefault("streamlit", streamlit_module)
sys.modules.setdefault("streamlit.components", components_module)
sys.modules.setdefault("streamlit.components.v1", components_v1_module)

import app_modules.ui_js as ui_js


class UiJsTests(unittest.TestCase):
    def setUp(self) -> None:
        iframe_calls.clear()
        html_calls.clear()
        importlib.reload(ui_js)

    def test_run_inline_script_uses_html_component_even_if_iframe_exists(self) -> None:
        ui_js.run_inline_script("console.log('hi')", height=7)

        self.assertEqual(iframe_calls, [])
        self.assertEqual(
            html_calls,
            [("<script>console.log('hi')</script>", 7, 0)],
        )

    def test_run_inline_script_ignores_blank_input(self) -> None:
        ui_js.run_inline_script("   ", height=3)

        self.assertEqual(iframe_calls, [])
        self.assertEqual(html_calls, [])


if __name__ == "__main__":
    unittest.main()
