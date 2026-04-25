import unittest

from logic.qobuz_app_id import (
    cache_qobuz_app_id,
    extract_qobuz_app_id,
    extract_qobuz_bundle_url,
    get_cached_qobuz_app_id,
    reset_cached_qobuz_app_id_for_tests,
)


class QobuzAppIdTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_cached_qobuz_app_id_for_tests()

    def tearDown(self) -> None:
        reset_cached_qobuz_app_id_for_tests()

    def test_extract_bundle_url_returns_absolute_qobuz_url(self) -> None:
        html = '<html><script src="/resources/123/bundle.js"></script></html>'
        self.assertEqual(
            extract_qobuz_bundle_url(html),
            "https://play.qobuz.com/resources/123/bundle.js",
        )

    def test_extract_qobuz_app_id_reads_production_api_value(self) -> None:
        bundle_js = 'window.config={"production":{"api":{"appId":"987654"}}};'
        self.assertEqual(extract_qobuz_app_id(bundle_js), "987654")

    def test_cache_qobuz_app_id_uses_shared_single_source_of_truth(self) -> None:
        self.assertEqual(get_cached_qobuz_app_id(), "")
        cache_qobuz_app_id("24680")
        self.assertEqual(get_cached_qobuz_app_id(), "24680")


if __name__ == "__main__":
    unittest.main()
