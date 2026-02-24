import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.settings import AppSettings
from core.service import ImportService
from core.parser import parse_line
from core.filter import LogFilter

def test_headless():
    settings = AppSettings(
        log_file_path="test_log.txt",
        output_folder_path=".",
        mode="import",
        append_description=True,
        avoid_duplicates=True,
        min_tracks=0,
        min_duration=0
    )
    
    # Test parser
    with open("test_log.txt", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    print("Testing Parser:")
    for line in lines:
        entry = parse_line(line)
        if entry:
            print(f"Parsed: {entry.url} | Tracks: {entry.track_count} | Duration: {entry.duration_min} | Year: {entry.release_date} | Free: {entry.free_flag}")
        else:
            print(f"Skipped line: {line.strip()}")
            
    # Test Filter
    print("\nTesting Filter:")
    filt = LogFilter(settings)
    for line in lines:
        entry = parse_line(line)
        if entry:
            valid = filt.is_valid(entry)
            print(f"Valid: {valid} - {entry.url}")

    # Test Import Service
    print("\nTesting Import Service:")
    svc = ImportService(settings, update_callback=lambda msg: print(f"Import Update: {msg}"))
    out_file = "export_test.txt"
    if os.path.exists(out_file):
        os.remove(out_file)
    svc.run("test_log.txt", out_file)
    
    print("\nExported Content (1st run):")
    with open(out_file, "r", encoding="utf-8") as f:
        print(f.read())
        
    print("Testing duplicates avoidance (2nd run):")
    svc.run("test_log.txt", out_file)
    with open(out_file, "r", encoding="utf-8") as f:
        print(f.read())

if __name__ == "__main__":
    test_headless()
