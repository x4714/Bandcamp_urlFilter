import re
LOG_LINE_PATTERN = re.compile(
    r'^\[(.*?)\]\s+<([^>]+)>\s+<(http[^>]+)>\s+(.*?)\s+-\s+(.*?)\s+\[(.*)\]\s*$'
)
lines = [
    "[10:20:30] <MyUser> <https://example.bandcamp.com/album/xyz> My Artist - My Title [mygenre|12|1h15m|2026-05-01|free]",
    "[10:20:30] <MyUser> https://example.bandcamp.com/album/xyz My Artist - My Title [mygenre|12|1h15m|2026-05-01|free]"
]

with open("test_out2.txt", "w") as f:
    for line in lines:
        m = LOG_LINE_PATTERN.match(line)
        f.write(f"Line: {line}\nMatched: {bool(m)}\n")
