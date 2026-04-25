from __future__ import annotations

import asyncio
import os
from typing import Optional

import aiohttp

from app_modules.debug_logging import emit_debug
from app_modules.env_utils import env_float, env_int
from logic.gazelle_api import GazelleAPI
from logic.metadata_scraper import HostRateLimiter, scrape_bandcamp_metadata
from logic.proxy_utils import create_connector_for_proxy, get_proxy
from logic.qobuz_matcher import match_album

STATUS_ERROR_SCRAPING = "⚠️ Error scraping Bandcamp"
STATUS_QOBUZ_AUTH_REQUIRED = "⚠️ Qobuz auth required"
STATUS_QOBUZ_CONFIG_ERROR = "⚠️ Qobuz configuration error"
STATUS_MATCHED = "✅ Matched"
STATUS_NO_MATCH = "❌ No Match on Qobuz"


def _matching_debug(message: str) -> None:
    emit_debug("matching", message)


async def process_single_entry(
    bandcamp_session: aiohttp.ClientSession,
    qobuz_session: aiohttp.ClientSession,
    entry,
    rate_limiter: HostRateLimiter,
    semaphore: asyncio.Semaphore,
    trackers: list[GazelleAPI] | None = None,
    only_24bit: bool = False,
    qobuz_max_retries: int = 3,
    qobuz_base_delay: float = 10.0,
    bc_max_retries: int = 5,
    bc_base_delay: float = 10.0,
    bandcamp_proxy: Optional[str] = None,
    qobuz_proxy: Optional[str] = None,
):
    _matching_debug(f"Processing single entry: `{entry.url}`")
    async with semaphore:
        bc_data = await scrape_bandcamp_metadata(
            entry.url, bandcamp_session, rate_limiter=rate_limiter,
            max_retries=bc_max_retries, base_delay=bc_base_delay,
            proxy=bandcamp_proxy,
        )
    if bc_data.get("status") != "success":
        _matching_debug(f"Bandcamp scrape failed for `{entry.url}`.")
        return {
            "Artist": entry.artist,
            "Album": entry.title,
            "UPC": None,
            "Bandcamp Link": entry.url,
            "Qobuz Link": "",
            "Status": STATUS_ERROR_SCRAPING,
        }

    match_data = await match_album(
        qobuz_session, bc_data, only_24bit=only_24bit,
        max_retries=qobuz_max_retries, base_delay=qobuz_base_delay,
        proxy=qobuz_proxy,
    )
    if match_data.get("status") == "authentication_required":
        _matching_debug(f"Qobuz auth missing while matching `{entry.url}`.")
        return {
            "Artist": bc_data.get("artist"),
            "Album": bc_data.get("album"),
            "UPC": None,
            "Bandcamp Link": bc_data.get("url"),
            "Qobuz Link": "",
            "Status": STATUS_QOBUZ_AUTH_REQUIRED,
        }
    if match_data.get("status") == "configuration_error":
        _matching_debug(f"Qobuz configuration error while matching `{entry.url}`.")
        return {
            "Artist": bc_data.get("artist"),
            "Album": bc_data.get("album"),
            "UPC": None,
            "Bandcamp Link": bc_data.get("url"),
            "Qobuz Link": "",
            "Status": STATUS_QOBUZ_CONFIG_ERROR,
        }
    if match_data.get("status") == "matched":
        _matching_debug(f"Match found for `{entry.url}`.")
        artist = match_data.get("qobuz_artist") or bc_data.get("artist")
        album = match_data.get("qobuz_album") or bc_data.get("album")
        upc = match_data.get("upc")

        status = STATUS_MATCHED
        if trackers:
            results = []
            for tracker in trackers:
                _is_dupe, info = await tracker.search_duplicates(artist, album, upc=upc)
                if info:
                    results.append(info)

            if results:
                status = " | ".join([STATUS_MATCHED] + results)

        return {
            "Artist": artist,
            "Album": album,
            "UPC": upc,
            "Bandcamp Link": bc_data.get("url"),
            "Qobuz Link": match_data.get("qobuz_url"),
            "Status": status,
        }

    _matching_debug(f"No Qobuz match for `{entry.url}`.")
    return {
        "Artist": bc_data.get("artist"),
        "Album": bc_data.get("album"),
        "UPC": None,
        "Bandcamp Link": bc_data.get("url"),
        "Qobuz Link": "",
        "Status": STATUS_NO_MATCH,
    }


async def process_batch(
    entries,
    progress_callback=None,
    check_dupes: bool = False,
    existing_trackers: list[GazelleAPI] | None = None,
    only_24bit: bool = False,
    concurrency: Optional[int] = None,
    min_interval_seconds: Optional[float] = None,
    qobuz_max_retries: Optional[int] = None,
    qobuz_base_delay: Optional[float] = None,
    bc_max_retries: Optional[int] = None,
    bc_base_delay: Optional[float] = None,
):
    _matching_debug(f"process_batch() called with {len(entries)} entry(ies), check_dupes={check_dupes}.")
    concurrency = int(concurrency) if concurrency is not None else env_int("BANDCAMP_CONCURRENCY", 2)
    min_interval_seconds = (
        float(min_interval_seconds)
        if min_interval_seconds is not None
        else env_float("BANDCAMP_MIN_INTERVAL_SECONDS", 1.0)
    )
    qobuz_max_retries = int(qobuz_max_retries) if qobuz_max_retries is not None else 3
    qobuz_base_delay = float(qobuz_base_delay) if qobuz_base_delay is not None else 10.0
    bc_max_retries = int(bc_max_retries) if bc_max_retries is not None else 5
    bc_base_delay = float(bc_base_delay) if bc_base_delay is not None else 10.0

    bandcamp_proxy = get_proxy("bandcamp")
    qobuz_proxy = get_proxy("qobuz")

    trackers = list(existing_trackers or []) if check_dupes else []

    if check_dupes and not trackers:
        red_key = os.getenv("RED_API_KEY", "")
        ops_key = os.getenv("OPS_API_KEY", "")
        red_url = os.getenv("RED_URL", "https://redacted.sh").rstrip("/")
        ops_url = os.getenv("OPS_URL", "https://orpheus.network").rstrip("/")

        if red_key:
            trackers.append(GazelleAPI("RED", red_url, api_key=red_key))
        if ops_key:
            trackers.append(GazelleAPI("OPS", ops_url, api_key=ops_key))

    _matching_debug(
        f"Matching runtime config: concurrency={concurrency}, min_interval_seconds={min_interval_seconds}, "
        f"qobuz_max_retries={qobuz_max_retries}, qobuz_base_delay={qobuz_base_delay}, trackers={len(trackers)}, "
        f"bandcamp_proxy={'set' if bandcamp_proxy else 'none'}, qobuz_proxy={'set' if qobuz_proxy else 'none'}."
    )
    semaphore = asyncio.Semaphore(concurrency)
    rate_limiter = HostRateLimiter(min_interval_seconds=min_interval_seconds)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
    }
    bandcamp_connector = create_connector_for_proxy(
        bandcamp_proxy,
        limit=max(concurrency * 2, 4),
        limit_per_host=concurrency,
    )
    qobuz_connector = create_connector_for_proxy(
        qobuz_proxy,
        limit=max(concurrency * 2, 4),
        limit_per_host=concurrency,
    )
    tasks: list[asyncio.Task] = []
    opened_trackers: list[GazelleAPI] = []
    try:
        if trackers:
            for tracker in trackers:
                await tracker.open()
                opened_trackers.append(tracker)

        async with (
            aiohttp.ClientSession(connector=bandcamp_connector, headers=headers) as bandcamp_session,
            aiohttp.ClientSession(connector=qobuz_connector, headers=headers) as qobuz_session,
        ):
            tasks = [
                asyncio.create_task(process_single_entry(
                    bandcamp_session, qobuz_session, entry, rate_limiter, semaphore,
                    trackers=trackers, only_24bit=only_24bit,
                    qobuz_max_retries=qobuz_max_retries, qobuz_base_delay=qobuz_base_delay,
                    bc_max_retries=bc_max_retries, bc_base_delay=bc_base_delay,
                    bandcamp_proxy=bandcamp_proxy, qobuz_proxy=qobuz_proxy,
                ))
                for entry in entries
            ]
            rows = []
            total = len(tasks)
            done = 0
            for task in asyncio.as_completed(tasks):
                try:
                    row = await task
                except Exception:
                    for pending_task in tasks:
                        if not pending_task.done():
                            pending_task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise

                rows.append(row)
                done += 1
                if progress_callback:
                    progress_callback(done, total, row)
            _matching_debug(f"process_batch() completed: processed={done}, total={total}.")
            return rows
    finally:
        if tasks:
            for pending_task in tasks:
                if not pending_task.done():
                    pending_task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        for tracker in opened_trackers:
            try:
                await tracker.close()
            except Exception as close_error:
                _matching_debug(
                    f"Tracker close failed for `{tracker.site_name}` and was ignored during cleanup: {close_error}"
                )
