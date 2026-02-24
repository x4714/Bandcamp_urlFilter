import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.parser import parse_line
from core.filter import LogFilter
from core.settings import AppSettings

line = "[10:20:30] <MyUser> <https://example.bandcamp.com/album/xyz> My Artist - My Title [mygenre|12|1h15m|2026-05-01|free]"

entry = parse_line(line)

with open('parser_out.txt', 'w', encoding='utf-8') as f:
    f.write(f"Parsed Entry: {entry}\n")

    if entry:
        settings = AppSettings(
            mode="import",
            append_description=True,
            avoid_duplicates=True,
            min_tracks=0,
            min_duration=0
        )
        filt = LogFilter(settings)
        valid = filt.is_valid(entry)
        f.write(f"Is Valid: {valid}\n")
        
        # Let's see why it might not be valid
        f.write(f"Bandcamp in URL: {'bandcamp' in entry.url.lower()}\n")
        
        meta_lower = entry.meta_raw.lower()
        f.write(f"2026 check: {'2026' in entry.release_date or '2026' in meta_lower}\n")
        f.write(f"Release Date: {entry.release_date}\n")
        f.write(f"Meta lower: {meta_lower}\n")
        
        f.write(f"Free check: {entry.free_flag.lower() == 'free' or 'free' in meta_lower}\n")
        f.write(f"Free Flag: {entry.free_flag}\n")
        
        if entry.track_count is not None:
            f.write(f"Track Count check: {entry.track_count} >= min_tracks(0)\n")
        else:
            f.write(f"Track Count check: None\n")
            
        if entry.duration_min is not None:
            f.write(f"Duration check: {entry.duration_min} >= min_duration(0)\n")
        else:
            f.write(f"Duration check: None\n")
