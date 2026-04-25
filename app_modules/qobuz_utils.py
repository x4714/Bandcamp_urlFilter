import hashlib
import hmac
from datetime import datetime, timezone

SECONDS_PER_DAY = 24 * 60 * 60
TOKEN_FINGERPRINT_KEY = b"bandcamp-urlfilter-token-fingerprint-v1"


def _parse_utc_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(f"{raw[:-1]}+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _qobuz_account_days_until_expiry(expires_at_iso: str) -> int | None:
    expires_at = _parse_utc_datetime(expires_at_iso)
    if expires_at is None:
        return None
    seconds_left = (expires_at - datetime.now(timezone.utc)).total_seconds()
    return int(seconds_left // SECONDS_PER_DAY)


def _token_fingerprint(token: str) -> str:
    raw_token = str(token or "")
    if not raw_token:
        return ""
    digest = hmac.new(
        TOKEN_FINGERPRINT_KEY,
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:16]
