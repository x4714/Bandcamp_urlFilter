from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, date

ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
LOG_LINE_PATTERN = re.compile(
    r'^\s*\[(.*?)\]\s+<([^>]+)>\s*(?:\d+)?\s*<(http[^>]+)>\s+(.*?)?\s*-\s*(.*?)?\s*\[([^\]]*)\](?:\s+.*)?$'
)
LOG_LINE_PATTERN_ALT = re.compile(
    r'^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+<([^>]+)>\s*(?:\d+)?\s*<(http[^>]+)>\s+(.*?)?\s*-\s*(.*?)?\s*\[([^\]]*)\](?:\s+.*)?$'
)
URL_ONLY_PATTERN = re.compile(r'^\s*(https?://[^\s]+)\s*$')

@dataclass
class LogEntry:
    timestamp: str
    user: str
    url: str
    artist: str
    title: str
    meta_raw: str
    genre: str = ""
    track_count: int | None = None
    duration_min: int | None = None
    release_date: date | None = None
    free_flag: str = ""
    original_line: str = ""


def clean_ansi(text: str) -> str:
    text = ANSI_ESCAPE_PATTERN.sub('', text)
    text = re.sub(r'\x03(\d{1,2}(,\d{1,2})?)?', '', text)
    text = re.sub(r'[\x02\x1D\x1F\x16\x0F]', '', text)
    return text


def parse_duration(duration_str: str) -> int | None:
    if not duration_str:
        return None
    total_minutes = 0
    duration_str = duration_str.lower().strip()

    h_match = re.search(r'(\d+)h', duration_str)
    if h_match:
        total_minutes += int(h_match.group(1)) * 60

    m_match = re.search(r'(\d+)m', duration_str)
    if m_match:
        total_minutes += int(m_match.group(1))

    if not h_match and not m_match and duration_str.isdigit():
        return int(duration_str)

    return total_minutes if total_minutes > 0 else None


def parse_line(line: str) -> LogEntry | None:
    clean_line = clean_ansi(line).strip()
    if clean_line.startswith('***'):
        return None

    match = LOG_LINE_PATTERN.match(clean_line)
    if not match:
        match = LOG_LINE_PATTERN_ALT.match(clean_line)

    if not match:
        url_match = URL_ONLY_PATTERN.match(clean_line)
        if not url_match:
            return None
        url = url_match.group(1).strip()
        return LogEntry(
            timestamp="",
            user="",
            url=url,
            artist="",
            title="",
            meta_raw="",
            original_line=line.strip()
        )

    timestamp, user, url, artist, title, meta_raw = match.groups()

    entry = LogEntry(
        timestamp=timestamp.strip(),
        user=user.strip(),
        url=url.strip(),
        artist=artist.strip(),
        title=title.strip(),
        meta_raw=meta_raw.strip(),
        original_line=line.strip()
    )

    if entry.meta_raw:
        parts = [p.strip() for p in entry.meta_raw.split('|')]
        if len(parts) > 0:
            entry.genre = parts[0]
        if len(parts) > 1 and parts[1].isdigit():
            entry.track_count = int(parts[1])
        if len(parts) > 2:
            entry.duration_min = parse_duration(parts[2])
        if len(parts) > 3:
            try:
                entry.release_date = datetime.strptime(parts[3].strip(), '%Y-%m-%d').date()
            except (ValueError, IndexError):
                entry.release_date = None
        if len(parts) > 4:
            entry.free_flag = parts[4]

    return entry


def filter_entries(lines: list[str], filters: dict[str, object]) -> list[LogEntry]:
    """
    Applies filters to raw log lines and returns valid LogEntry objects.
    filters dict can optionally contain:
      - tag (str): filter by genre/tag (checks meta_raw)
      - location (str): filter by location (checks meta_raw)
      - min_tracks (int): minimum track count
      - max_tracks (int): maximum track count
      - free_mode (str): 'Free', 'Paid', or 'All'
    """
    results = []

    tag_filter_str = filters.get("tag", "")
    include_tags = [t.strip().lower() for t in tag_filter_str.split(',')] if tag_filter_str.strip() else []

    exclude_tag_str = filters.get("exclude_tag", "")
    exclude_tags = [t.strip().lower() for t in exclude_tag_str.split(',')] if exclude_tag_str.strip() else []

    location_filter = filters.get("location", "").lower().strip()
    min_tracks = filters.get("min_tracks")
    max_tracks = filters.get("max_tracks")
    min_duration = filters.get("min_duration")
    max_duration = filters.get("max_duration")
    free_mode = filters.get("free_mode", "All").lower()

    for line in lines:
        if not line.strip():
            continue

        entry = parse_line(line)
        if not entry:
            continue

        if 'bandcamp' not in entry.url.lower():
            continue

        meta_lower = entry.meta_raw.lower()
        genre_lower = entry.genre.lower()

        if include_tags:
            if not any(t in genre_lower or t in meta_lower for t in include_tags):
                continue

        if exclude_tags:
            if any(t in genre_lower or t in meta_lower for t in exclude_tags):
                continue

        if location_filter and location_filter not in meta_lower:
            continue

        if min_tracks is not None and (entry.track_count is None or entry.track_count < min_tracks):
            continue

        if max_tracks is not None and (entry.track_count is None or entry.track_count > max_tracks):
            continue

        if min_duration is not None and (entry.duration_min is None or entry.duration_min < min_duration):
            continue

        if max_duration is not None and (entry.duration_min is None or entry.duration_min > max_duration):
            continue

        if free_mode in ["free", "paid"]:
            flag = entry.free_flag.strip().lower()
            if free_mode == "free" and flag != "free":
                continue
            if free_mode == "paid" and flag == "free":
                continue

        results.append(entry)

    return results
