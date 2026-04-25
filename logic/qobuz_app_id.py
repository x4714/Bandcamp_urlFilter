from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import threading
from typing import Any, Awaitable

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


class QobuzAppIdCache:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._cached_app_id = ""
        self._discovery_in_flight = False
        self._discovery_status = ""

    def get_cached_app_id(self) -> str:
        with self._condition:
            return self._cached_app_id

    def cache_app_id(self, app_id: str) -> str:
        cleaned_app_id = str(app_id or "").strip()
        if not cleaned_app_id:
            return ""
        with self._condition:
            self._cached_app_id = cleaned_app_id
            self._condition.notify_all()
        return cleaned_app_id

    def clear(self) -> None:
        with self._condition:
            self._cached_app_id = ""
            self._discovery_in_flight = False
            self._discovery_status = ""
            self._condition.notify_all()

    def set_status(self, message: str) -> None:
        with self._condition:
            self._discovery_status = str(message or "").strip()
            self._condition.notify_all()

    def read_discovery_state(self) -> tuple[str, bool, str]:
        with self._condition:
            return self._cached_app_id, self._discovery_in_flight, self._discovery_status

    def begin_discovery(self) -> bool:
        with self._condition:
            if self._cached_app_id or self._discovery_in_flight:
                return False
            self._discovery_in_flight = True
            return True

    def finish_discovery(self) -> None:
        with self._condition:
            self._discovery_in_flight = False
            self._condition.notify_all()

    def wait_for_update(self, timeout: float = 0.25) -> None:
        with self._condition:
            self._condition.wait(timeout=timeout)


_APP_ID_CACHE = QobuzAppIdCache()


class _BackgroundAsyncRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
            self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            with self._lock:
                self._loop = None
                self._thread = None
                self._ready.clear()

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            loop = self._loop
            thread = self._thread
            if loop is not None and thread is not None and thread.is_alive() and not loop.is_closed():
                return loop
            self._ready.clear()
            thread = threading.Thread(target=self._thread_main, daemon=True, name="qobuz-app-id-runner")
            self._thread = thread
            thread.start()
        self._ready.wait()
        loop = self._loop
        if loop is None:
            raise RuntimeError("Background async runner failed to start.")
        return loop

    def run(self, awaitable: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        loop = self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(awaitable, loop)
        try:
            return future.result()
        except concurrent.futures.CancelledError as exc:
            raise RuntimeError("Background Qobuz App ID task was cancelled.") from exc


_ASYNC_RUNNER = _BackgroundAsyncRunner()


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
    return _APP_ID_CACHE.get_cached_app_id()


def cache_qobuz_app_id(app_id: str) -> str:
    return _APP_ID_CACHE.cache_app_id(app_id)


def clear_cached_qobuz_app_id() -> None:
    _APP_ID_CACHE.clear()


def _set_discovery_status(message: str) -> None:
    _APP_ID_CACHE.set_status(message)


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
    return _ASYNC_RUNNER.run(awaitable)


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

    last_seen_status = ""
    while True:
        cached_app_id, in_flight, status_message = _APP_ID_CACHE.read_discovery_state()
        if cached_app_id:
            if status_callback is not None:
                try:
                    status_callback("Using shared auto-discovered Qobuz App ID.")
                except Exception:
                    logger.debug("Ignoring Qobuz App ID status callback failure.", exc_info=True)
            return cached_app_id
        if not in_flight and _APP_ID_CACHE.begin_discovery():
            break
        _APP_ID_CACHE.wait_for_update(timeout=0.25)

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
        _APP_ID_CACHE.finish_discovery()
