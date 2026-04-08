import aiohttp
import asyncio
import time
from typing import Optional, Dict, Any

class GazelleAPI:
    def __init__(self, site_name: str, site_url: str, api_key: str = "", session_cookie: str = "", rate_limit_seconds: float = 2.0):
        self.site_name = site_name
        self.site_url = site_url.rstrip("/")
        self.api_key = api_key
        self.session_cookie = session_cookie.strip().strip("'").strip('"')
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_time = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self.failed = False
        self.last_error = ""

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            cookies = {}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Referer": f"{self.site_url}/"
            }

            if self.api_key:
                # API Key is the preferred method for automated tools
                headers["Authorization"] = self.api_key
            elif self.session_cookie:
                # Fallback to session cookie if no API Key is provided
                val = self.session_cookie
                if val.startswith("session="):
                    val = val.split("session=")[1].split(";")[0]
                cookies["session"] = val
            
            self._session = aiohttp.ClientSession(cookies=cookies, headers=headers)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, params: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if self.failed:
            return None, f"Aborted: {self.site_name} is in a failed state ({self.last_error})"

        # Enforce rate limit
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            await asyncio.sleep(self.rate_limit_seconds - elapsed)
        
        if not self.api_key and not self.session_cookie:
            return None, "No API Key or Session Cookie configured."

        await self._ensure_session()
        self._last_request_time = time.monotonic()
        
        try:
            async with self._session.get(
                f"{self.site_url}/ajax.php", 
                params=params, 
                timeout=15,
                allow_redirects=False
            ) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        if data.get("status") == "success":
                            return data.get("response"), None
                        
                        err = data.get('error', 'Unknown error')
                        if response.status == 403 or "not logged in" in str(err).lower():
                            self.failed = True
                            self.last_error = f"Auth Error: {err}"
                        return None, f"API Error: {err}"
                    except Exception as e:
                        return None, f"JSON Parse Error: {str(e)}"
                elif response.status in (301, 302):
                    loc = response.headers.get("Location", "")
                    self.failed = True
                    self.last_error = f"Redirect to {loc}"
                    
                    if "login.php" in loc:
                        return None, "Login required (Session expired?)"
                    return None, f"Anti-bot/Redirect to {loc}"
                elif response.status == 403:
                    self.failed = True
                    self.last_error = "403 Forbidden"
                    return None, "Forbidden (403). Tracker might be blocking this IP or Session."
                elif response.status == 429:
                    return None, "Rate limited (429)."
                return None, f"HTTP {response.status}"
        except Exception as e:
            return None, f"Request Exception: {str(e)}"

    async def search_duplicates(self, artist: str, album: str, upc: Optional[str] = None) -> tuple[bool, str]:
        """
        Searches the tracker for a potential duplicate.
        Returns (is_dupe, status_message).
        """
        if self.failed:
            return False, f"⚠️ {self.site_name} Disabled: {self.last_error}"

        if not self.api_key and not self.session_cookie:
            return False, ""
            
        # 1. Try search by UPC (if provided)
        if upc:
            params = {
                "action": "browse",
                "upc": upc
            }
            response, error = await self._request(params)
            if response:
                if self._has_lossless_in_results(response.get("results", [])):
                    return True, f"Dupe found via UPC on {self.site_name}"
            elif self.failed:
                 return False, f"⚠️ {self.site_name} Failed during UPC search: {self.last_error}"
            
        # 2. Fallback to Artist + Album search
        search_str = f"{artist} {album}".strip()
        params = {
            "action": "browse",
            "searchstr": search_str
        }
        
        response, error = await self._request(params)
        if error:
            return False, f"⚠️ {self.site_name} Error: {error}"
            
        if response and self._has_lossless_in_results(response.get("results", [])):
            return True, f"Dupe found on {self.site_name}"
            
        return False, ""

    def _has_lossless_in_results(self, results: list) -> bool:
        if not results:
            return False
            
        for group in results:
            torrents = group.get("torrents", [])
            for torrent in torrents:
                fmt = str(torrent.get("format", "")).upper()
                enc = str(torrent.get("encoding", "")).upper()
                if fmt == "FLAC" and enc in ["LOSSLESS", "24BIT LOSSLESS"]:
                    return True
        return False
