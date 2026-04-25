import hashlib
import unittest

from app_modules import qobuz_utils


class QobuzUtilsTests(unittest.TestCase):
    def test_token_fingerprint_matches_sha256_prefix(self) -> None:
        token = "abc123"
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        self.assertEqual(qobuz_utils.token_fingerprint(token), expected)

    def test_legacy_aliases_match_public_helpers(self) -> None:
        self.assertEqual(qobuz_utils._token_fingerprint("x"), qobuz_utils.token_fingerprint("x"))
        self.assertEqual(
            qobuz_utils._parse_utc_datetime("2025-01-01T00:00:00Z"),
            qobuz_utils.parse_utc_datetime("2025-01-01T00:00:00Z"),
        )
        self.assertEqual(
            qobuz_utils._qobuz_account_days_until_expiry("2999-01-01T00:00:00Z"),
            qobuz_utils.qobuz_account_days_until_expiry("2999-01-01T00:00:00Z"),
        )


if __name__ == "__main__":
    unittest.main()
