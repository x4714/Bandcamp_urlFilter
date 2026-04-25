from __future__ import annotations

import asyncio
import logging
import os
import time

import aiohttp
from rapidfuzz import fuzz

from logic.qobuz_app_id import discover_qobuz_app_id_async, get_cached_qobuz_app_id
from logic.proxy_utils import proxy_request_kwargs

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
QOBUZ_FUZZY_MATCH_THRESHOLD = 80
QOBUZ_HIRES_MINIMUM_BIT_DEPTH = 24
QOBUZ_SEARCH_LIMIT = 10
STATUS_AUTH_MISSING = "auth_missing"
STATUS_APP_ID_MISSING = "app_id_missing"
STATUS_SEARCH_ERROR = "search_error"


async def _auto_discover_qobuz_app_id(session: aiohttp.ClientSession, proxy: str | None = None) -> str:
    cached_app_id = get_cached_qobuz_app_id()
    if cached_app_id:
        return cached_app_id
    return await discover_qobuz_app_id_async(session, proxy=proxy)


def get_qobuz_credentials() -> tuple[str, str]:
    app_id = os.getenv("QOBUZ_APP_ID", "")
    user_token = os.getenv("QOBUZ_USER_AUTH_TOKEN", "")
    return app_id, user_token


async def search_qobuz(
    session: aiohttp.ClientSession,
    query: str,
    max_retries: int = 3,
    base_delay: float = 10.0,
    proxy: str | None = None,
) -> dict:
    url = "https://www.qobuz.com/api.json/0.2/catalog/search"
    qobuz_app_id, qobuz_user_auth_token = get_qobuz_credentials()
    if not qobuz_app_id:
        qobuz_app_id = await _auto_discover_qobuz_app_id(session, proxy=proxy)
    if not qobuz_app_id:
        logger.warning("QOBUZ_APP_ID is missing and auto-discovery failed.")
        return {
            "status": STATUS_APP_ID_MISSING,
            "error_msg": "QOBUZ_APP_ID is missing and auto-discovery failed.",
            "albums": {"items": []},
        }
    if not qobuz_user_auth_token:
        logger.warning("QOBUZ_USER_AUTH_TOKEN is missing; skipping Qobuz search for query %r.", query)
        return {
            "status": STATUS_AUTH_MISSING,
            "error_msg": "QOBUZ_USER_AUTH_TOKEN is not configured.",
            "albums": {"items": []},
        }

    params = {
        "query": query,
        "limit": QOBUZ_SEARCH_LIMIT,
        "offset": 0,
    }
    headers = {"X-App-Id": qobuz_app_id}
    if qobuz_user_auth_token:
        headers["X-User-Auth-Token"] = qobuz_user_auth_token

    for attempt in range(max_retries):
        try:
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                **proxy_request_kwargs(proxy),
            ) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    data = await response.json(content_type=None)
                    albums_payload = data.get("albums") if isinstance(data, dict) else None
                    if not isinstance(albums_payload, dict):
                        logger.warning(
                            "Qobuz search returned HTTP 200 with unexpected payload for query %r "
                            "(content_type=%r, payload_type=%s).",
                            query,
                            content_type,
                            type(data).__name__,
                        )
                        return {
                            "status": STATUS_SEARCH_ERROR,
                            "error_msg": "Unexpected Qobuz payload shape.",
                            "albums": {"items": []},
                        }
                    return data

                if response.status in (429, 500, 502, 503, 504):
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Qobuz transient HTTP %s for query %r. Retrying in %ss...",
                        response.status,
                        query,
                        delay,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                    continue

                logger.warning("Qobuz API returned %s for query: %s", response.status, query)
                return {
                    "status": STATUS_SEARCH_ERROR,
                    "error_msg": f"Qobuz API returned HTTP {response.status}.",
                    "albums": {"items": []},
                }
        except asyncio.TimeoutError:
            delay = base_delay * (2 ** attempt)
            logger.warning("Qobuz timeout for query %r. Retrying in %ss...", query, delay)
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        except Exception as exc:
            logger.exception("Unexpected error fetching Qobuz search results for query %r: %s", query, exc)
            return {
                "status": STATUS_SEARCH_ERROR,
                "error_msg": str(exc),
                "albums": {"items": []},
            }

    return {
        "status": STATUS_SEARCH_ERROR,
        "error_msg": "Qobuz search exhausted retries.",
        "albums": {"items": []},
    }

def is_match(bandcamp_data: dict, qobuz_album: dict, only_24bit: bool = False) -> bool:
    """Matches Qobuz API album data against parsed Bandcamp data."""
    if not qobuz_album:
        return False

    album_title = qobuz_album.get("title", "Unknown")
    current_timestamp = time.time()

    # 1. Base Streamable Check
    if not qobuz_album.get("streamable", False):
        logger.debug("Skipped %r: Not streamable flag is False.", album_title)
        return False

    # 2. 24-bit availability check (opt-in)
    if only_24bit:
        hires_streamable = qobuz_album.get("hires_streamable", False)
        max_bit_depth = qobuz_album.get("maximum_bit_depth", 0) or 0
        if not hires_streamable and max_bit_depth < QOBUZ_HIRES_MINIMUM_BIT_DEPTH:
            logger.debug(
                "Skipped %r: Not available in 24-bit (hires_streamable=%s, max_bit_depth=%s).",
                album_title,
                hires_streamable,
                max_bit_depth,
            )
            return False

    # 3. Release Date Check (Exclude Pre-orders)
    # released_at is a Unix timestamp. If in the future, it's a pre-order.
    released_at = qobuz_album.get("released_at")
    if released_at and released_at > current_timestamp:
        release_date_str = time.strftime("%Y-%m-%d", time.gmtime(released_at))
        logger.debug("Skipped %r: Pre-order (Released at %s).", album_title, release_date_str)
        return False

    # 4. Completeness Check (Exclude Partially Streamable Albums)
    # Compare streamable_count with tracks_count if available.
    tracks_count = qobuz_album.get("tracks_count", 0)
    streamable_count = qobuz_album.get("streamable_count")

    tracks_payload = qobuz_album.get("tracks")
    if streamable_count is None and isinstance(tracks_payload, dict):
        items = tracks_payload.get("items")
        if isinstance(items, list):
            streamable_count = len(items)
        else:
            streamable_count = tracks_payload.get("count")
    elif streamable_count is None and isinstance(tracks_payload, list):
        streamable_count = len(tracks_payload)

    if streamable_count is not None and tracks_count > 0:
        if streamable_count < tracks_count:
            logger.debug(
                "Skipped %r: Partial streaming (%s/%s tracks).",
                album_title,
                streamable_count,
                tracks_count,
            )
            return False

    qb_artist = qobuz_album.get("artist", {}).get("name", "")
    qb_album = album_title
    qb_tracks = qobuz_album.get("tracks_count", 0)

    bc_artist = bandcamp_data.get("artist", "")
    bc_album = bandcamp_data.get("album", "") or bandcamp_data.get("track", "")
    bc_tracks = bandcamp_data.get("track_count", 0)

    # 5. Track Count Comparison
    # Requirement: EXACT MATCH
    if qb_tracks != bc_tracks and bc_tracks > 0:
        logger.debug(
            "Skipped %r: Track count mismatch (Qobuz: %s, Bandcamp: %s).",
            album_title,
            qb_tracks,
            bc_tracks,
        )
        return False

    # 6. Fuzzy Title & Artist Matching
    artist_score = fuzz.token_sort_ratio(qb_artist.lower(), bc_artist.lower())
    album_score = fuzz.token_sort_ratio(qb_album.lower(), bc_album.lower())

    if artist_score > QOBUZ_FUZZY_MATCH_THRESHOLD and album_score > QOBUZ_FUZZY_MATCH_THRESHOLD:
        return True

    logger.debug(
        "Skipped %r: Fuzzy score too low (Artist: %s, Album: %s).",
        album_title,
        artist_score,
        album_score,
    )
    return False


async def match_album(
    session: aiohttp.ClientSession,
    bandcamp_data: dict,
    only_24bit: bool = False,
    max_retries: int = 3,
    base_delay: float = 1.5,
    proxy: str | None = None,
) -> dict:
    """Takes Bandcamp metadata, queries Qobuz, and returns match dict."""
    if bandcamp_data.get("status") != "success":
        return {"status": "no_bandcamp_metadata", "url": bandcamp_data.get("url")}
    if bandcamp_data.get("is_single"):
        return {
            "status": "no_match",
            "bandcamp_url": bandcamp_data.get("url"),
            "qobuz_url": "",
        }

    artist = bandcamp_data.get("artist", "")
    album = bandcamp_data.get("album", "")

    query = f"{artist} {album}"
    search_results = await search_qobuz(
        session,
        query,
        max_retries=max_retries,
        base_delay=base_delay,
        proxy=proxy,
    )
    search_status = str(search_results.get("status", "")).strip().lower()
    if search_status == STATUS_AUTH_MISSING:
        return {
            "status": "authentication_required",
            "bandcamp_url": bandcamp_data.get("url"),
            "qobuz_url": "",
            "error_msg": str(search_results.get("error_msg", "")),
        }
    if search_status == STATUS_APP_ID_MISSING:
        return {
            "status": "configuration_error",
            "bandcamp_url": bandcamp_data.get("url"),
            "qobuz_url": "",
            "error_msg": str(search_results.get("error_msg", "")),
        }

    albums = search_results.get("albums", {}).get("items", [])

    for qb_album in albums:
        if is_match(bandcamp_data, qb_album, only_24bit=only_24bit):
            url_str = f"https://www.qobuz.com/album/-/{qb_album.get('id')}"
            # Some versions of Qobuz APIs return human readable URLs or just the ID:
            # So fallback to ID if no slug.
            return {
                "status": "matched",
                "qobuz_url": url_str,
                "qobuz_artist": qb_album.get("artist", {}).get("name"),
                "qobuz_album": qb_album.get("title"),
                "qobuz_id": qb_album.get("id"),
                "upc": qb_album.get("upc") or qb_album.get("barcode"),
                "bandcamp_url": bandcamp_data.get("url"),
            }

    return {
        "status": "no_match",
        "bandcamp_url": bandcamp_data.get("url"),
        "qobuz_url": "",
    }
