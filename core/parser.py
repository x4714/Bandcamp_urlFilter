import re
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, date

# Pattern to match ANSI escape codes (often used in IRC/terminals for colors)
ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Pattern to parse the generic log line structure:
# [Timestamp] <User> <URL> Artist - Title [Meta]
LOG_LINE_PATTERN = re.compile(
    r'^\s*\[(.*?)\]\s+<([^>]+)>\s*(?:\d+)?\s*<(http[^>]+)>\s+(.*?)?\s*-\s*(.*?)?\s*(?:\d+)?\s*\[([^\]]*)\](?:\s+.*)?$'
)

@dataclass
class LogEntry:
    timestamp: str
    user: str
    url: str
    artist: str
    title: str
    meta_raw: str
    genre: str = ""
    track_count: Optional[int] = None
    duration_min: Optional[int] = None
    release_date: Optional[date] = None
    free_flag: str = ""
    original_line: str = ""

def clean_ansi(text: str) -> str:
    """Remove ANSI color codes and Control Characters like IRC color formatting."""
    # Remove standard ANSI escapes
    text = ANSI_ESCAPE_PATTERN.sub('', text)
    # Remove IRC specific color/formatting codes (Ctrl+C, Ctrl+B, Ctrl+O, etc.)
    # \x03 is color, followed by optional fg/bg codes like 04,05
    text = re.sub(r'\x03(\d{1,2}(,\d{1,2})?)?', '', text)
    # Bold, Italic, Underline, Reset
    text = re.sub(r'[\x02\x1D\x1F\x16\x0F]', '', text)
    return text

def parse_duration(duration_str: str) -> Optional[int]:
    """Converts a duration string like '1h5m' or '30m' to total minutes."""
    if not duration_str:
        return None
    
    total_minutes = 0
    duration_str = duration_str.lower().strip()
    
    # Extract hours
    h_match = re.search(r'(\d+)h', duration_str)
    if h_match:
        total_minutes += int(h_match.group(1)) * 60
        
    # Extract minutes
    m_match = re.search(r'(\d+)m', duration_str)
    if m_match:
        total_minutes += int(m_match.group(1))
        
    # If it's just a number without 'm', assume minutes
    if not h_match and not m_match and duration_str.isdigit():
        return int(duration_str)
        
    if total_minutes > 0:
        return total_minutes
    return None

def parse_line(line: str) -> Optional[LogEntry]:
    """Parses a raw log line into a LogEntry object."""
    clean_line = clean_ansi(line).strip()
    
    # Ignore system messages
    if clean_line.startswith('***'):
        return None
        
    match = LOG_LINE_PATTERN.match(clean_line)
    if not match:
        return None
        
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
    
    # Parse meta_raw if it exists
    if entry.meta_raw:
        parts = [p.strip() for p in entry.meta_raw.split('|')]
        # Expected format: Genre | TrackCount | Duration | ReleaseDate | FreeFlag
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
