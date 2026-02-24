from typing import Optional
from core.parser import LogEntry
from core.settings import AppSettings

class LogFilter:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    def is_valid(self, entry: LogEntry) -> bool:
        """
        Evaluates if the LogEntry matches all specified criteria:
        1. URL must contain 'bandcamp'
        2. Release date is 2026 OR meta string contains '2026'
        3. FreeFlag is 'free' OR meta string contains 'free'
        4. Track count >= Min tracks (if defined)
        5. Duration >= Min duration (if defined)
        """
        if not entry:
            return False

        # 1. Bandcamp mandatory
        if 'bandcamp' not in entry.url.lower():
            return False

        meta_lower = entry.meta_raw.lower()

        # 2. Year 2026
        if '2026' not in entry.release_date and '2026' not in meta_lower:
            return False

        # 3. Free
        if entry.free_flag.lower() != 'free' and 'free' not in meta_lower:
            return False

        # 4. Min Tracks
        if self.settings.min_tracks is not None:
            if entry.track_count is None or entry.track_count < self.settings.min_tracks:
                return False

        # 5. Min Duration
        if self.settings.min_duration is not None:
            if entry.duration_min is None or entry.duration_min < self.settings.min_duration:
                return False

        return True
