import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


aiohttp_module = types.ModuleType("aiohttp")
aiohttp_module.ClientTimeout = lambda total=0: {"total": total}
aiohttp_module.ClientSession = object
sys.modules.setdefault("aiohttp", aiohttp_module)

from logic.metadata_scraper import (
    SCRAPE_STATUS_FETCH_FAILED,
    SCRAPE_STATUS_JSON_LD_NOT_FOUND,
    SCRAPE_STATUS_SUCCESS,
    scrape_bandcamp_metadata,
)


class MetadataScraperTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_failure_returns_normalized_result(self) -> None:
        with patch("logic.metadata_scraper.fetch_with_retries", AsyncMock(return_value="")):
            result = await scrape_bandcamp_metadata("https://artist.bandcamp.com/album/test", session=object())

        self.assertEqual(result["status"], SCRAPE_STATUS_FETCH_FAILED)
        self.assertEqual(result["url"], "https://artist.bandcamp.com/album/test")
        self.assertEqual(result["artist"], "")
        self.assertEqual(result["album"], "")
        self.assertEqual(result["track"], "")
        self.assertEqual(result["track_count"], 0)
        self.assertFalse(result["is_single"])
        self.assertIn("error_msg", result)

    async def test_album_success_returns_normalized_result(self) -> None:
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {"@type":"MusicAlbum","name":"Album","numTracks":7,"datePublished":"2024-05-01","byArtist":{"name":"Artist"}}
            </script>
          </head>
        </html>
        """
        with patch("logic.metadata_scraper.fetch_with_retries", AsyncMock(return_value=html)):
            result = await scrape_bandcamp_metadata("https://artist.bandcamp.com/album/test", session=object())

        self.assertEqual(result["status"], SCRAPE_STATUS_SUCCESS)
        self.assertEqual(result["artist"], "Artist")
        self.assertEqual(result["album"], "Album")
        self.assertEqual(result["track"], "")
        self.assertEqual(result["track_count"], 7)
        self.assertEqual(result["year"], "2024")
        self.assertFalse(result["is_single"])
        self.assertEqual(result["error_msg"], "")

    async def test_missing_json_ld_returns_normalized_result(self) -> None:
        with patch("logic.metadata_scraper.fetch_with_retries", AsyncMock(return_value="<html></html>")):
            result = await scrape_bandcamp_metadata("https://artist.bandcamp.com/album/test", session=object())

        self.assertEqual(result["status"], SCRAPE_STATUS_JSON_LD_NOT_FOUND)
        self.assertEqual(result["url"], "https://artist.bandcamp.com/album/test")
        self.assertEqual(result["artist"], "")
        self.assertEqual(result["album"], "")
        self.assertEqual(result["track"], "")
        self.assertEqual(result["track_count"], 0)
        self.assertFalse(result["is_single"])


if __name__ == "__main__":
    unittest.main()
