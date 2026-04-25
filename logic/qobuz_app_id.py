import asyncio
import logging
import re
import threading
from typing import Any

import aiohttp

from logic.proxy_utils import create_connector_for_proxy, proxy_request_kwargs


logger = logging.getLogger(__name__)
QOBUZ_WEB_PLAYER_URL = "https://play.qobuz.com/"
QOBUZ_APP_ID_DISCOVERY_TIMEOUT = aiohttp.ClientTimeout(total=10)
QOBUZ_WEB_PLAYER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
}
_BUNDLE_PATH_PATTERN = re.compile(r'src="(/resources/[^"]*bundle\.js)"')
_APP_ID_PATTERN = re.compile(
    r'"?production"?\s*:\s*\{.*?"?api"?\s*:\s*\{.*?"?appId"?\s*:\s*"(\d+)"',
    re.DOTALL,
)
_DISCOVERY_CONDITION = threading.Condition()
_CACHED_QOBUZ_APP_ID = ""
_DISCOVERY_IN_FLIGHT = False
_DISCOVERY_STATUS = ""


def extract_qobuz_bundle_url(player_html: str) -> str:
    bundle_match = _BUNDLE_PATH_PATTERN.search(player_html or "")
    if not bundle_match:
        return ""
    return f"https://play.qobuz.com{bundle_match.group(1)}"


def extract_qobuz_app_id(bundle_js: str) -> str:
    production_match = _APP_ID_PATTERN.search(bundle_js or "")
    if not production_match:
        return ""
    return production_match.group(1)


def get_cached_qobuz_app_id() -> str:
    with _DISCOVERY_CONDITION:
        return _CACHED_QOBUZ_APP_ID


def cache_qobuz_app_id(app_id: str) -> str:
    cleaned_app_id = str(app_id or "").strip()
    if not cleaned_app_id:
        return ""

    global _CACHED_QOBUZ_APP_ID
    with _DISCOVERY_CONDITION:
        _CACHED_QOBUZ_APP_ID = cleaned_app_id
        _DISCOVERY_CONDITION.notify_all()
    return cleaned_app_id


def reset_cached_qobuz_app_id_for_tests() -> None:
    global _CACHED_QOBUZ_APP_ID, _DISCOVERY_IN_FLIGHT, _DISCOVERY_STATUS
    with _DISCOVERY_CONDITION:
        _CACHED_QOBUZ_APP_ID = ""
        _DISCOVERY_IN_FLIGHT = False
        _DISCOVERY_STATUS = ""
        _DISCOVERY_CONDITION.notify_all()


def _set_discovery_status(message: str) -> None:
    global _DISCOVERY_STATUS
    with _DISCOVERY_CONDITION:
        _DISCOVERY_STATUS = str(message or "").strip()
        _DISCOVERY_CONDITION.notify_all()


def _emit_discovery_status(message: str, status_callback: Any = None) -> None:
    text = str(message or "").strip()
    if not text:
        return
    _set_discovery_status(text)
    if status_callback is not None:
        try:
            status_callback(text)
        except Exception:
            logger.debug("Ignoring Qobuz App ID status callback failure.", exc_info=True)


def _run_coroutine_sync(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: list[Any] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # pragma: no cover - defensive bridge for UI runtimes
            error.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


async def discover_qobuz_app_id_async(
    session: aiohttp.ClientSession,
    proxy: str | None = None,
) -> str:
    cached_app_id = get_cached_qobuz_app_id()
    if cached_app_id:
        return cached_app_id

    try:
        async with session.get(
            QOBUZ_WEB_PLAYER_URL,
            headers=QOBUZ_WEB_PLAYER_HEADERS,
            timeout=QOBUZ_APP_ID_DISCOVERY_TIMEOUT,
            **proxy_request_kwargs(proxy),
        ) as response:
            if response.status != 200:
                logger.warning("Qobuz web player returned HTTP %s during App ID discovery.", response.status)
                return ""
            html = await response.text()
    except asyncio.TimeoutError:
        logger.warning("Timed out while fetching the Qobuz web player for App ID discovery.")
        return ""
    except aiohttp.ClientError as exc:
        logger.warning("Qobuz App ID discovery request failed: %s", exc)
        return ""
    except Exception:
        logger.exception("Unexpected error fetching the Qobuz web player during App ID discovery.")
        return ""

    bundle_url = extract_qobuz_bundle_url(html)
    if not bundle_url:
        logger.warning("Could not locate the Qobuz web player bundle while discovering the App ID.")
        return ""

    try:
        async with session.get(
            bundle_url,
            headers=QOBUZ_WEB_PLAYER_HEADERS,
            timeout=QOBUZ_APP_ID_DISCOVERY_TIMEOUT,
            **proxy_request_kwargs(proxy),
        ) as response:
            if response.status != 200:
                logger.warning("Qobuz bundle returned HTTP %s during App ID discovery.", response.status)
                return ""
            bundle_js = await response.text()
    except asyncio.TimeoutError:
        logger.warning("Timed out while fetching the Qobuz bundle for App ID discovery.")
        return ""
    except aiohttp.ClientError as exc:
        logger.warning("Qobuz bundle request failed during App ID discovery: %s", exc)
        return ""
    except Exception:
        logger.exception("Unexpected error fetching the Qobuz bundle during App ID discovery.")
        return ""

    app_id = extract_qobuz_app_id(bundle_js)
    if not app_id:
        logger.warning("Qobuz App ID discovery completed, but no App ID pattern was found in the bundle.")
        return ""
    return cache_qobuz_app_id(app_id)


def discover_qobuz_app_id_sync(
    status_callback: Any = None,
    proxy: str | None = None,
) -> str:
    cached_app_id = get_cached_qobuz_app_id()
    if cached_app_id:
        _emit_discovery_status("Using cached auto-discovered Qobuz App ID.", status_callback)
        return cached_app_id

    global _DISCOVERY_IN_FLIGHT
    last_seen_status = ""
    while True:
        with _DISCOVERY_CONDITION:
            cached_app_id = _CACHED_QOBUZ_APP_ID
            in_flight = _DISCOVERY_IN_FLIGHT
            status_message = _DISCOVERY_STATUS
            if cached_app_id:
                if status_callback is not None:
                    try:
                        status_callback("Using shared auto-discovered Qobuz App ID.")
                    except Exception:
                        logger.debug("Ignoring Qobuz App ID status callback failure.", exc_info=True)
                return cached_app_id
            if not in_flight:
                _DISCOVERY_IN_FLIGHT = True
                break
            _DISCOVERY_CONDITION.wait(timeout=0.25)

        if status_message and status_message != last_seen_status and status_callback is not None:
            try:
                status_callback(status_message)
            except Exception:
                logger.debug("Ignoring Qobuz App ID status callback failure.", exc_info=True)
            last_seen_status = status_message

    try:
        _emit_discovery_status("Fetching Qobuz App ID from play.qobuz.com...", status_callback)

        async def _discover() -> str:
            connector = create_connector_for_proxy(proxy)
            async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
                return await discover_qobuz_app_id_async(session, proxy=proxy)

        app_id = str(_run_coroutine_sync(_discover()) or "").strip()
        if app_id:
            _emit_discovery_status("Qobuz App ID discovered from web player.", status_callback)
        return app_id
    finally:
        with _DISCOVERY_CONDITION:
            _DISCOVERY_IN_FLIGHT = False
            _DISCOVERY_CONDITION.notify_all()
