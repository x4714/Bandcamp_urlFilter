import os
import asyncio
import aiohttp
import logging
import re
import time
from rapidfuzz import fuzz
from dotenv import load_dotenv
from logic.proxy_utils import proxy_request_kwargs

logger = logging.getLogger(__name__)
load_dotenv()
_AUTO_DISCOVERED_APP_ID: str = ""
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _auto_discover_qobuz_app_id(session: aiohttp.ClientSession, proxy: str | None = None) -> str:
    global _AUTO_DISCOVERED_APP_ID
    if _AUTO_DISCOVERED_APP_ID:
        return _AUTO_DISCOVERED_APP_ID

    try:
        async with session.get(
            "https://play.qobuz.com/",
            timeout=REQUEST_TIMEOUT,
            **proxy_request_kwargs(proxy),
        ) as response:
            if response.status != 200:
                return ""
            html = await response.text()
    except Exception:
        return ""

    bundle_match = re.search(r'src="(/resources/[^"]*bundle\.js)"', html)
    if not bundle_match:
        return ""

    bundle_url = f"https://play.qobuz.com{bundle_match.group(1)}"
    try:
        async with session.get(bundle_url, timeout=REQUEST_TIMEOUT, **proxy_request_kwargs(proxy)) as response:
            if response.status != 200:
                return ""
            js = await response.text()
    except Exception:
        return ""

    production_match = re.search(
        r'"?production"?\s*:\s*\{.*?"?api"?\s*:\s*\{.*?"?appId"?\s*:\s*"(\d+)"',
        js,
        re.DOTALL
    )
    if not production_match:
        return ""

    _AUTO_DISCOVERED_APP_ID = production_match.group(1)
    return _AUTO_DISCOVERED_APP_ID

def get_qobuz_credentials() -> tuple[str, str]:
    # Reload values so .env edits are picked up without restarting Streamlit.
    load_dotenv(override=True)
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
        return {}

    params = {
        "query": query,
        "limit": 10,
        "offset": 0
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
                    data = await response.json()
                    return data

                if response.status in (429, 500, 502, 503, 504):
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Qobuz transient HTTP {response.status} for query '{query}'. Retrying in {delay}s..."
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                    continue

                logger.warning(f"Qobuz API returned {response.status} for query: {query}")
                return {}
        except asyncio.TimeoutError:
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Qobuz timeout for query '{query}'. Retrying in {delay}s...")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        except Exception as e:
            logger.error(f"Error fetching from Qobuz: {e}")
            return {}

    return {}

def is_match(bandcamp_data: dict, qobuz_album: dict, only_24bit: bool = False) -> bool:
    """Matches Qobuz API album data against parsed Bandcamp data."""
    if not qobuz_album:
        return False

    album_title = qobuz_album.get("title", "Unknown")

    # 1. Base Streamable Check
    if not qobuz_album.get("streamable", False):
        logger.debug(f"Skipped '{album_title}': Not streamable flag is False.")
        return False

    # 2. 24-bit availability check (opt-in)
    if only_24bit:
        hires_streamable = qobuz_album.get("hires_streamable", False)
        max_bit_depth = qobuz_album.get("maximum_bit_depth", 0) or 0
        if not hires_streamable and max_bit_depth < 24:
            logger.debug(f"Skipped '{album_title}': Not available in 24-bit (hires_streamable={hires_streamable}, max_bit_depth={max_bit_depth}).")
            return False
        
    # 3. Release Date Check (Exclude Pre-orders)
    # released_at is a Unix timestamp. If in the future, it's a pre-order.
    released_at = qobuz_album.get("released_at")
    if released_at and released_at > time.time():
        release_date_str = time.strftime('%Y-%m-%d', time.gmtime(released_at))
        logger.debug(f"Skipped '{album_title}': Pre-order (Released at {release_date_str}).")
        return False

    # 4. Completeness Check (Exclude Partially Streamable Albums)
    # Compare streamable_count with tracks_count if available.
    tracks_count = qobuz_album.get("tracks_count", 0)
    streamable_count = qobuz_album.get("streamable_count")
    
    # Fallback: if 'tracks' exists as a list (some API versions), check its length
    if streamable_count is None and "tracks" in qobuz_album and isinstance(qobuz_album["tracks"], dict):
        # Sometimes 'tracks' is a dict with 'items'
        streamable_count = qobuz_album["tracks"].get("count")

    if streamable_count is not None and tracks_count > 0:
        if streamable_count < tracks_count:
            logger.debug(f"Skipped '{album_title}': Partial streaming ({streamable_count}/{tracks_count} tracks).")
            return False

    qb_artist = qobuz_album.get("artist", {}).get("name", "")
    qb_album = qobuz_album.get("title", "")
    qb_tracks = qobuz_album.get("tracks_count", 0)
    
    bc_artist = bandcamp_data.get("artist", "")
    bc_album = bandcamp_data.get("album", "")
    bc_tracks = bandcamp_data.get("track_count", 0)
    
    # 5. Track Count Comparison
    # Requirement: EXACT MATCH
    if qb_tracks != bc_tracks and bc_tracks > 0:
        logger.debug(f"Skipped '{album_title}': Track count mismatch (Qobuz: {qb_tracks}, Bandcamp: {bc_tracks}).")
        return False

    # 6. Fuzzy Title & Artist Matching
    artist_score = fuzz.token_sort_ratio(qb_artist.lower(), bc_artist.lower())
    album_score = fuzz.token_sort_ratio(qb_album.lower(), bc_album.lower())
    
    if artist_score > 80 and album_score > 80:
        return True
        
    logger.debug(f"Skipped '{album_title}': Fuzzy score too low (Artist: {artist_score}, Album: {album_score}).")
    return False

async def match_album(session: aiohttp.ClientSession, bandcamp_data: dict, only_24bit: bool = False, max_retries: int = 3, base_delay: float = 1.5, proxy: str | None = None) -> dict:
    """Takes Bandcamp metadata, queries Qobuz, and returns match dict."""
    if bandcamp_data.get("status") != "success":
        return {"status": "no_bandcamp_metadata", "url": bandcamp_data.get("url")}

    artist = bandcamp_data.get("artist", "")
    album = bandcamp_data.get("album", "")

    query = f"{artist} {album}"
    search_results = await search_qobuz(session, query, max_retries=max_retries, base_delay=base_delay, proxy=proxy)

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
                "bandcamp_url": bandcamp_data.get("url")
            }
            
    return {
        "status": "no_match",
        "bandcamp_url": bandcamp_data.get("url"),
        "qobuz_url": ""
    }
