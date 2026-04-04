import os
import aiohttp
import logging
from rapidfuzz import fuzz
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

def get_qobuz_credentials() -> tuple[str, str]:
    # Reload values so .env edits are picked up without restarting Streamlit.
    load_dotenv(override=True)
    app_id = os.getenv("QOBUZ_APP_ID", "100000000")
    user_token = os.getenv("QOBUZ_USER_AUTH_TOKEN", "")
    return app_id, user_token

async def search_qobuz(session: aiohttp.ClientSession, query: str) -> dict:
    url = "https://www.qobuz.com/api.json/0.2/catalog/search"
    qobuz_app_id, qobuz_user_auth_token = get_qobuz_credentials()
    params = {
        "query": query,
        "limit": 10,
        "offset": 0
    }
    headers = {"X-App-Id": qobuz_app_id}
    if qobuz_user_auth_token:
        headers["X-User-Auth-Token"] = qobuz_user_auth_token
    
    try:
        async with session.get(url, params=params, headers=headers, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                logger.warning(f"Qobuz API returned {response.status} for query: {query}")
                return {}
    except Exception as e:
        logger.error(f"Error fetching from Qobuz: {e}")
        return {}

def is_match(bandcamp_data: dict, qobuz_album: dict) -> bool:
    """Matches Qobuz API album data against parsed Bandcamp data."""
    if not qobuz_album:
        return False

    # Only match if the album is streamable on Qobuz
    if not qobuz_album.get("streamable", False):
        return False
        
    qb_artist = qobuz_album.get("artist", {}).get("name", "")
    qb_album = qobuz_album.get("title", "")
    qb_tracks = qobuz_album.get("tracks_count", 0)
    
    bc_artist = bandcamp_data.get("artist", "")
    bc_album = bandcamp_data.get("album", "")
    bc_tracks = bandcamp_data.get("track_count", 0)
    
    # Track Count logic: Exact match OR track count is very close (+- 1)
    # The requirement is EXACT MATCH
    if qb_tracks != bc_tracks and bc_tracks > 0:
        return False

    # Fuzzy Title & Artist Matching
    artist_score = fuzz.token_sort_ratio(qb_artist.lower(), bc_artist.lower())
    album_score = fuzz.token_sort_ratio(qb_album.lower(), bc_album.lower())
    
    # You can adjust these thresholds as necessary (85 is generally a good "Very similar" threshold)
    if artist_score > 80 and album_score > 80:
        return True
        
    return False

async def match_album(session: aiohttp.ClientSession, bandcamp_data: dict) -> dict:
    """Takes Bandcamp metadata, queries Qobuz, and returns match dict."""
    if bandcamp_data.get("status") != "success":
        return {"status": "no_bandcamp_metadata", "url": bandcamp_data.get("url")}
        
    artist = bandcamp_data.get("artist", "")
    album = bandcamp_data.get("album", "")
    
    # Try searching logic
    # Qobuz search sometimes works best with just Artist + Album
    query = f"{artist} {album}"
    search_results = await search_qobuz(session, query)
    
    albums = search_results.get("albums", {}).get("items", [])
    
    for qb_album in albums:
        if is_match(bandcamp_data, qb_album):
            url_str = f"https://www.qobuz.com/album/-/{qb_album.get('id')}"
            # Some versions of Qobuz APIs return human readable URLs or just the ID:
            # So fallback to ID if no slug.
            return {
                "status": "matched",
                "qobuz_url": url_str,
                "qobuz_artist": qb_album.get("artist", {}).get("name"),
                "qobuz_album": qb_album.get("title"),
                "qobuz_id": qb_album.get("id"),
                "bandcamp_url": bandcamp_data.get("url")
            }
            
    return {
        "status": "no_match",
        "bandcamp_url": bandcamp_data.get("url"),
        "qobuz_url": ""
    }
