import unittest
from datetime import date

from app_modules.filtering import build_filtered_entries


class BuildFilteredEntriesTests(unittest.TestCase):
    def test_date_filter_keeps_entries_with_missing_release_date_and_tracks_counters(self) -> None:
        lines = [
            "[2024-01-01] <user> <https://artist.bandcamp.com/album/in-range> Artist - In Range [ambient | 8 | 40m | 2024-06-01 | free]",
            "[2024-01-01] <user> <https://artist.bandcamp.com/album/out-of-range> Artist - Out of Range [ambient | 8 | 40m | 2023-05-01 | free]",
            "https://artist.bandcamp.com/album/url-only",
            "[2024-01-01] <user> <https://artist.bandcamp.com/album/bad-date> Artist - Bad Date [ambient | 8 | 40m | not-a-date | free]",
        ]

        entries, stats = build_filtered_entries(
            lines,
            filter_config={},
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        self.assertEqual(
            [entry.url for entry in entries],
            [
                "https://artist.bandcamp.com/album/in-range",
                "https://artist.bandcamp.com/album/url-only",
                "https://artist.bandcamp.com/album/bad-date",
            ],
        )
        self.assertEqual(stats["date_filter_active"], True)
        self.assertEqual(stats["date_filtered_out"], 1)
        self.assertEqual(stats["missing_release_date"], 2)

    def test_no_date_filter_reports_zero_date_stats(self) -> None:
        lines = [
            "[2024-01-01] <user> <https://artist.bandcamp.com/album/in-range> Artist - In Range [ambient | 8 | 40m | 2024-06-01 | free]",
            "https://artist.bandcamp.com/album/url-only",
        ]

        entries, stats = build_filtered_entries(
            lines,
            filter_config={},
            start_date=None,
            end_date=None,
        )

        self.assertEqual(len(entries), 2)
        self.assertEqual(stats["date_filter_active"], False)
        self.assertEqual(stats["date_filtered_out"], 0)
        self.assertEqual(stats["missing_release_date"], 0)


if __name__ == "__main__":
    unittest.main()
