import os

from dotenv import load_dotenv


def get_proxy(service: str = "global") -> str | None:
    """
    Returns the proxy URL for the given service, or None if not configured.

    Env vars (all optional, all default off):
      GLOBAL_PROXY   — fallback for every service
      BANDCAMP_PROXY — overrides GLOBAL_PROXY for Bandcamp requests
      QOBUZ_PROXY    — overrides GLOBAL_PROXY for Qobuz requests
      TRACKER_PROXY  — overrides GLOBAL_PROXY for RED/OPS tracker requests

    Format: http://user:pass@host:port  (or socks5://, https://)
    """
    load_dotenv(override=True)
    global_proxy = os.getenv("GLOBAL_PROXY", "").strip() or None
    specific = os.getenv(f"{service.upper()}_PROXY", "").strip() or None
    return specific or global_proxy
