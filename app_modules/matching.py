import asyncio
import os

import aiohttp

from logic.metadata_scraper import HostRateLimiter, scrape_bandcamp_metadata
from logic.qobuz_matcher import match_album


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
):
    async with semaphore:
        bc_data = await scrape_bandcamp_metadata(entry.url, session, rate_limiter=rate_limiter)
    if bc_data.get("status") != "success":
        return {
            "Artist": entry.artist,
            "Album": entry.title,
            "Bandcamp Link": entry.url,
            "Qobuz Link": "",
            "Status": "⚠️ Error scraping Bandcamp",
        }

    match_data = await match_album(session, bc_data)
    if match_data.get("status") == "matched":
        return {
            "Artist": bc_data.get("artist"),
            "Album": bc_data.get("album"),
            "Bandcamp Link": bc_data.get("url"),
            "Qobuz Link": match_data.get("qobuz_url"),
            "Status": "✅ Matched",
        }

    return {
        "Artist": bc_data.get("artist"),
        "Album": bc_data.get("album"),
        "Bandcamp Link": bc_data.get("url"),
        "Qobuz Link": "",
        "Status": "❌ No Match on Qobuz",
    }


async def process_batch(entries):
    concurrency = _env_int("BANDCAMP_CONCURRENCY", 2)
    min_interval_seconds = _env_float("BANDCAMP_MIN_INTERVAL_SECONDS", 1.0)
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
        tasks = [
            asyncio.create_task(process_single_entry(session, entry, rate_limiter, semaphore))
            for entry in entries
        ]
        rows = []
        for task in asyncio.as_completed(tasks):
            rows.append(await task)
        return rows
