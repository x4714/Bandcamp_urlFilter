import json
import asyncio
from bs4 import BeautifulSoup
import aiohttp
import logging

logger = logging.getLogger(__name__)

async def fetch_with_retries(session: aiohttp.ClientSession, url: str, max_retries: int = 3, base_delay: float = 2.0) -> str:
    """Fetches text with exponential backoff on failure."""
    for attempt in range(max_retries):
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                elif response.status in (429, 500, 502, 503, 504):
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Transient HTTP {response.status} for {url}. Waiting {delay}s...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                else:
                    logger.warning(f"Failed to fetch {url}. Status: {response.status}")
                    return ""
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {url}.")
            delay = base_delay * (2 ** attempt)
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return ""
            
    return ""

async def scrape_bandcamp_metadata(url: str, session: aiohttp.ClientSession) -> dict:
    html = await fetch_with_retries(session, url)
    if not html:
        return {}
        
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for the JSON-LD script tag
        ld_json_tag = soup.find('script', type='application/ld+json')
        if ld_json_tag:
            data = json.loads(ld_json_tag.string)
            
            # The structure might be a list or a dict
            items = data if isinstance(data, list) else [data]
            
            for item in items:
                if item.get('@type') == 'MusicAlbum':
                    artist_obj = item.get('byArtist', {})
                    artist_name = artist_obj.get('name', '')
                    num_tracks = item.get('numTracks', 0)
                    date_published = item.get('datePublished', '')
                    name = item.get('name', '')
                    
                    return {
                        "artist": artist_name,
                        "album": name,
                        "track_count": num_tracks,
                        "year": date_published.split()[0][:4] if date_published else "",
                        "url": url,
                        "status": "success"
                    }
                    
                # Handle single tracks if applicable
                elif item.get('@type') == 'MusicRecording':
                    artist_obj = item.get('byArtist', {})
                    artist_name = artist_obj.get('name', '')
                    date_published = item.get('datePublished', '')
                    name = item.get('name', '')
                    
                    return {
                        "artist": artist_name,
                        "album": name, # It's a single track
                        "track_count": 1,
                        "year": date_published.split()[0][:4] if date_published else "",
                        "url": url,
                        "status": "success"
                    }
                    
        return {"status": "json_ld_not_found", "url": url}

    except Exception as e:
        logger.error(f"Error parsing metadata for {url}: {e}")
        return {"status": "error", "error_msg": str(e), "url": url}
