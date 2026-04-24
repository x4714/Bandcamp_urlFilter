import os
from typing import Any
from urllib.parse import urlparse

import aiohttp
from dotenv import load_dotenv

try:
    from aiohttp_socks import ProxyConnector
except ImportError:  # pragma: no cover - handled at runtime for missing optional dep
    ProxyConnector = None


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


def is_socks_proxy(proxy: str | None) -> bool:
    if not proxy:
        return False
    return urlparse(proxy).scheme.lower() in {"socks4", "socks4a", "socks5", "socks5h"}


def proxy_request_kwargs(proxy: str | None) -> dict[str, Any]:
    if not proxy or is_socks_proxy(proxy):
        return {}
    return {"proxy": proxy}


def create_connector_for_proxy(proxy: str | None, **connector_kwargs: Any) -> aiohttp.BaseConnector:
    if is_socks_proxy(proxy):
        if ProxyConnector is None:
            raise RuntimeError("SOCKS proxy support requires the aiohttp-socks package.")
        return ProxyConnector.from_url(proxy, **connector_kwargs)
    return aiohttp.TCPConnector(**connector_kwargs)
