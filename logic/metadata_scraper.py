import json
import asyncio
import random
import time
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import aiohttp
import logging
from logic.proxy_utils import proxy_request_kwargs

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
SCRAPE_STATUS_SUCCESS = "success"
SCRAPE_STATUS_FETCH_FAILED = "fetch_failed"
SCRAPE_STATUS_JSON_LD_NOT_FOUND = "json_ld_not_found"
SCRAPE_STATUS_ERROR = "error"


def _scrape_result(status: str, url: str, **payload) -> dict:
    result = {
        "status": str(status or "").strip() or "error",
        "error_msg": "",
        "artist": "",
        "album": "",
        "track": "",
        "track_count": 0,
        "year": "",
        "is_single": False,
        "url": str(url or "").strip(),
    }
    result.update(payload)
    return result


class HostRateLimiter:
    """Applies a minimum delay between requests per host."""

    def __init__(self, min_interval_seconds: float = 1.0):
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._next_allowed_by_host = {}
        self._lock = asyncio.Lock()

    async def wait(self, url: str) -> None:
        if self.min_interval_seconds <= 0:
            return

        host = (urlparse(url).hostname or "").lower()
        if not host:
            return

        sleep_for = 0.0
        async with self._lock:
            now = time.monotonic()
            next_allowed = self._next_allowed_by_host.get(host, now)
            if next_allowed > now:
                sleep_for = next_allowed - now
                now = next_allowed
            self._next_allowed_by_host[host] = now + self.min_interval_seconds

        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


def _parse_retry_after_seconds(value: str) -> float:
    if not value:
        return 0.0

    value = value.strip()
    if not value:
        return 0.0

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            return 0.0
        delay = when.timestamp() - time.time()
        return max(0.0, delay)
    except Exception:
        return 0.0


async def fetch_with_retries(
    session: aiohttp.ClientSession,
    url: str,
    max_retries: int = 5,
    base_delay: float = 2.0,
    rate_limiter: Optional[HostRateLimiter] = None,
    proxy: Optional[str] = None,
) -> str:
    """Fetches text with exponential backoff on failure."""
    for attempt in range(max_retries):
        try:
            if rate_limiter is not None:
                await rate_limiter.wait(url)
            async with session.get(url, timeout=REQUEST_TIMEOUT, **proxy_request_kwargs(proxy)) as response:
                if response.status == 200:
                    return await response.text()
                elif response.status in (429, 500, 502, 503, 504):
                    retry_after_delay = _parse_retry_after_seconds(response.headers.get("Retry-After", ""))
                    exp_delay = base_delay * (2 ** attempt)
                    jitter = random.uniform(0, base_delay * 0.35)
                    delay = max(exp_delay, retry_after_delay) + jitter
                    logger.warning(
                        "Transient HTTP %s for %s (attempt %s/%s). Waiting %.1fs...",
                        response.status,
                        url,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                else:
                    logger.warning("Failed to fetch %s. Status: %s", url, response.status)
                    return ""
        except asyncio.TimeoutError:
            delay = (base_delay * (2 ** attempt)) + random.uniform(0, base_delay * 0.35)
            logger.warning("Timeout fetching %s (attempt %s/%s). Waiting %.1fs...", url, attempt + 1, max_retries, delay)
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)
            return ""
            
    return ""

async def scrape_bandcamp_metadata(
    url: str,
    session: aiohttp.ClientSession,
    rate_limiter: Optional[HostRateLimiter] = None,
    max_retries: int = 5,
    base_delay: float = 10.0,
    proxy: Optional[str] = None,
) -> dict:
    html = await fetch_with_retries(
        session,
        url,
        max_retries=max_retries,
        base_delay=base_delay,
        rate_limiter=rate_limiter,
        proxy=proxy,
    )
    if not html:
        return _scrape_result(SCRAPE_STATUS_FETCH_FAILED, url, error_msg="Could not fetch Bandcamp page.")
        
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for the JSON-LD script tag
        ld_json_tag = soup.find('script', type='application/ld+json')
        if ld_json_tag:
            raw_json = ld_json_tag.string or ld_json_tag.get_text(strip=True)
            if not raw_json:
                return _scrape_result(SCRAPE_STATUS_JSON_LD_NOT_FOUND, url)

            data = json.loads(raw_json)
            
            # The structure might be a list or a dict
            items = data if isinstance(data, list) else [data]
            
            for item in items:
                if item.get('@type') == 'MusicAlbum':
                    artist_obj = item.get('byArtist', {})
                    artist_name = artist_obj.get('name', '')
                    num_tracks = item.get('numTracks', 0)
                    date_published = item.get('datePublished', '')
                    name = item.get('name', '')

                    return _scrape_result(
                        SCRAPE_STATUS_SUCCESS,
                        url,
                        artist=artist_name,
                        album=name,
                        track_count=num_tracks,
                        year=date_published.split()[0][:4] if date_published else "",
                    )

                # Handle single tracks if applicable
                elif item.get('@type') == 'MusicRecording':
                    artist_obj = item.get('byArtist', {})
                    artist_name = artist_obj.get('name', '')
                    date_published = item.get('datePublished', '')
                    name = item.get('name', '')

                    return _scrape_result(
                        SCRAPE_STATUS_SUCCESS,
                        url,
                        artist=artist_name,
                        track=name,
                        track_count=1,
                        year=date_published.split()[0][:4] if date_published else "",
                        is_single=True,
                    )

        return _scrape_result(SCRAPE_STATUS_JSON_LD_NOT_FOUND, url)

    except Exception as exc:
        logger.error("Error parsing metadata for %s: %s", url, exc)
        return _scrape_result(SCRAPE_STATUS_ERROR, url, error_msg=str(exc))
