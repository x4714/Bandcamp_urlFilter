import asyncio
import os
from typing import List, Optional

import aiohttp

from app_modules.debug_logging import emit_debug
from logic.gazelle_api import GazelleAPI
from logic.metadata_scraper import HostRateLimiter, scrape_bandcamp_metadata
from logic.qobuz_matcher import match_album

STATUS_ERROR_SCRAPING = "⚠️ Error scraping Bandcamp"
STATUS_MATCHED = "✅ Matched"
STATUS_NO_MATCH = "❌ No Match on Qobuz"


def _matching_debug(message: str) -> None:
    emit_debug("matching", message)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


async def process_single_entry(
    session: aiohttp.ClientSession,
    entry,
    rate_limiter: HostRateLimiter,
    semaphore: asyncio.Semaphore,
    trackers: Optional[List[GazelleAPI]] = None,
):
    _matching_debug(f"Processing single entry: `{entry.url}`")
    async with semaphore:
        bc_data = await scrape_bandcamp_metadata(entry.url, session, rate_limiter=rate_limiter)
    if bc_data.get("status") != "success":
        _matching_debug(f"Bandcamp scrape failed for `{entry.url}`.")
        return {
            "Artist": entry.artist,
            "Album": entry.title,
            "Bandcamp Link": entry.url,
            "Qobuz Link": "",
            "Status": STATUS_ERROR_SCRAPING,
        }

    match_data = await match_album(session, bc_data)
    if match_data.get("status") == "matched":
        _matching_debug(f"Match found for `{entry.url}`.")
        artist = match_data.get("qobuz_artist") or bc_data.get("artist")
        album = match_data.get("qobuz_album") or bc_data.get("album")
        upc = match_data.get("upc")

        status = STATUS_MATCHED
        if trackers:
            results = []
            for tracker in trackers:
                is_dupe, info = await tracker.search_duplicates(artist, album, upc=upc)
                if info:
                    # info contains descriptive messages like "Dupe (UPC) @ RED"
                    results.append(info)

            if results:
                status += " | " + " | ".join(results)

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
        "Bandcamp Link": bc_data.get("url"),
        "Qobuz Link": "",
        "Status": STATUS_NO_MATCH,
    }


async def process_batch(entries, progress_callback=None, check_dupes: bool = False, existing_trackers: Optional[List[GazelleAPI]] = None):
    _matching_debug(f"process_batch() called with {len(entries)} entry(ies), check_dupes={check_dupes}.")
    concurrency = _env_int("BANDCAMP_CONCURRENCY", 2)
    min_interval_seconds = _env_float("BANDCAMP_MIN_INTERVAL_SECONDS", 1.0)

    trackers = existing_trackers or []
    trackers_created_locally = False

    if check_dupes and not trackers:
        trackers_created_locally = True
        # Load credentials from env
        red_key = os.getenv("RED_API_KEY", "")
        ops_key = os.getenv("OPS_API_KEY", "")
        red_url = os.getenv("RED_URL", "https://redacted.sh").rstrip("/")
        ops_url = os.getenv("OPS_URL", "https://orpheus.network").rstrip("/")

        if red_key:
            trackers.append(GazelleAPI("RED", red_url, api_key=red_key))
        if ops_key:
            trackers.append(GazelleAPI("OPS", ops_url, api_key=ops_key))

    _matching_debug(
        f"Matching runtime config: concurrency={concurrency}, min_interval_seconds={min_interval_seconds}, trackers={len(trackers)}."
    )
    semaphore = asyncio.Semaphore(concurrency)
    rate_limiter = HostRateLimiter(min_interval_seconds=min_interval_seconds)
    connector = aiohttp.TCPConnector(limit=max(concurrency * 2, 4), limit_per_host=concurrency)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
    }
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        try:
            tasks = [
                asyncio.create_task(process_single_entry(session, entry, rate_limiter, semaphore, trackers=trackers))
                for entry in entries
            ]
            rows = []
            total = len(tasks)
            done = 0
            for task in asyncio.as_completed(tasks):
                row = await task
                rows.append(row)
                done += 1
                if progress_callback:
                    progress_callback(done, total, row)
            _matching_debug(f"process_batch() completed: processed={done}, total={total}.")
            return rows
        finally:
            if trackers_created_locally:
                # Only close tracker sessions if we created them here.
                # Otherwise, the caller (who passed existing_trackers) is responsible.
                for tracker in trackers:
                    await tracker.close()
