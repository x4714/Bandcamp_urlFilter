import asyncio
import time
from typing import Any, Dict, Optional

import aiohttp


class GazelleAPI:
    def __init__(self, site_name: str, site_url: str, api_key: str = "", rate_limit_seconds: float = 2.0):
        self.site_name = site_name
        self.site_url = site_url.rstrip("/")
        self.api_key = api_key.strip().strip("'").strip('"')
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_time = 0.0
        self.failed = False
        self.last_error = ""
        self.authenticated = False

    async def close(self) -> None:
        # Requests currently use short-lived ClientSession instances, so there is
        # no persistent transport to tear down here. Keeping this method lets the
        # caller always follow a safe cleanup path.
        return

    async def authenticate(self) -> bool:
        """
        Performs an 'index' call to establish the connection and verify API Key.
        Matches smoked-salmon's behavior.
        """
        if self.failed:
            return False
        if self.authenticated:
            return True

        response, error = await self._request({"action": "index"})
        if error:
            # We don't set failed=True on 429, but on most others we do
            return False

        self.authenticated = True
        return True

    async def _request(self, params: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if self.failed:
            return None, f"Aborted: {self.site_name} is in a failed state ({self.last_error})"

        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            await asyncio.sleep(self.rate_limit_seconds - elapsed)

        if not self.api_key:
            return None, "No API Key configured."

        self._last_request_time = time.monotonic()

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": f"{self.site_url}/",
            "Connection": "close",
            "Authorization": self.api_key,
        }

        from app_modules.debug_logging import emit_debug

        emit_debug("gazelle_api", f"[{self.site_name}] Request params: {params}")

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    f"{self.site_url}/ajax.php",
                    params=params,
                    timeout=15,
                    allow_redirects=False,
                ) as response:
                    if response.status == 200:
                        try:
                            data = await response.json()
                            if data.get("status") == "success":
                                resp_data = data.get("response")
                                res_count = (
                                    len(resp_data.get("results", []))
                                    if resp_data and isinstance(resp_data, dict)
                                    else 0
                                )
                                emit_debug("gazelle_api", f"[{self.site_name}] Success. Results: {res_count}")
                                return resp_data, None

                            err = data.get("error", "Unknown error")
                            if response.status == 403 or "not logged in" in str(err).lower():
                                self.failed = True
                                self.last_error = f"Auth Error: {err}"
                            return None, f"API Error: {err}"
                        except Exception as e:
                            return None, f"JSON Parse Error: {e}"
                    if response.status in (301, 302):
                        loc = response.headers.get("Location", "")
                        self.failed = True
                        self.last_error = f"Redirect to {loc}"

                        if "login.php" in loc:
                            return None, "Login required (API Key invalid or Permission denied?)"
                        return None, f"Anti-bot/Redirect to {loc}"
                    if response.status == 403:
                        self.failed = True
                        self.last_error = "403 Forbidden"
                        return None, "Forbidden (403). Tracker might be blocking this IP or API Key."
                    if response.status == 429:
                        return None, "Rate limited (429)."
                    return None, f"HTTP {response.status}"
        except Exception as e:
            return None, f"Request Exception: {e}"

    async def search_duplicates(self, artist: str, album: str, upc: Optional[str] = None) -> tuple[bool, str]:
        """
        Searches the tracker for a potential duplicate.
        Returns (is_dupe, status_message).
        """
        if self.failed:
            return False, f"⚠️ {self.site_name} Disabled: {self.last_error}"

        if not self.api_key:
            return False, ""

        if not self.authenticated:
            # Ensure authentication/index call first
            success = await self.authenticate()
            if not success:
                return False, f"⚠️ {self.site_name} Auth Failed"

        # 1. Try search by UPC (if provided)
        if upc and str(upc).strip():
            params = {
                "action": "browse",
                "upc": str(upc).strip(),
            }
            response, error = await self._request(params)
            if response:
                if self._has_lossless_in_results(response.get("results", []), target_artist=artist):
                    return True, f"Dupe (UPC) @ {self.site_name}"
            elif self.failed:
                return False, f"⚠️ {self.site_name} Failed (UPC): {self.last_error}"

        # 2. Fallback to Precise Artist + Album search
        params = {
            "action": "browse",
            "artistname": artist.strip(),
            "groupname": album.strip(),
        }

        response, error = await self._request(params)
        if error:
            return False, f"⚠️ {self.site_name} Error: {error}"

        if response and self._has_lossless_in_results(response.get("results", [])):
            return True, f"Dupe (Artist/Album) @ {self.site_name}"

        return False, f"✅ {self.site_name}: No dupe"

    def _has_lossless_in_results(self, results: list, target_artist: Optional[str] = None) -> bool:
        if not results:
            return False

        for group in results:
            if target_artist:
                # Safety check: if searching by UPC, verify artist name to avoid shared barcode errors
                group_artist = str(group.get("artist", "")).lower()
                target_artist_lower = target_artist.lower()
                if target_artist_lower not in group_artist and group_artist not in target_artist_lower:
                    # If the result artist is completely different, skip this group
                    # (e.g. search for 'Jeddy Bear' but UPC matches 'Various Artists' or 'Other Guy')
                    continue

            torrents = group.get("torrents", [])
            for torrent in torrents:
                fmt = str(torrent.get("format", "")).upper()
                enc = str(torrent.get("encoding", "")).upper()
                # Ensure we strictly match FLAC/Lossless
                if fmt == "FLAC" and enc in ["LOSSLESS", "24BIT LOSSLESS"]:
                    return True
        return False
