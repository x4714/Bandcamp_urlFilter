import unittest

from logic.bandcamp_filter import filter_entries


class BandcampFilterTests(unittest.TestCase):
    def test_filter_entries_applies_tag_free_and_dedup_friendly_rules(self) -> None:
        lines = [
            "[2024-01-01] <user> <https://artist.bandcamp.com/album/one> Artist - Album One [ambient | 8 | 42m | 2024-01-02 | free]",
            "[2024-01-01] <user> <https://artist.bandcamp.com/album/two> Artist - Album Two [techno | 6 | 30m | 2024-01-02 | paid]",
            "[2024-01-01] <user> <https://example.com/not-music> Artist - Ignore [ambient | 8 | 42m | 2024-01-02 | free]",
        ]

        results = filter_entries(
            lines,
            {
                "tag": "ambient",
                "exclude_tag": "drone",
                "min_tracks": 5,
                "max_tracks": 10,
                "min_duration": 40,
                "max_duration": 50,
                "free_mode": "Free",
            },
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://artist.bandcamp.com/album/one")


if __name__ == "__main__":
    unittest.main()
