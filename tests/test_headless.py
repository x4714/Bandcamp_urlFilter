import os
import sys

# Add the parent directory to sys.path so we can import 'core'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.settings import AppSettings
from core.service import ImportService
from core.parser import parse_line
from core.filter import LogFilter

def test_headless():
    # Use paths relative to the project root or provide absolute paths
    # For testing, we expect test_log.txt in the project root
    log_path = os.path.join(os.path.dirname(__file__), "..", "test_log.txt")
    
    settings = AppSettings(
        log_file_path=log_path,
        output_folder_path=".",
        mode="import",
        append_description=True,
        avoid_duplicates=True,
        min_tracks=0,
        min_duration=0
    )
    
    if not os.path.exists(log_path):
        print(f"Error: test_log.txt not found at {log_path}")
        return

    # Test parser
    with open(log_path, "r", encoding="utf-8") as f:
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
    svc.run(log_path, out_file)
    
    print("\nExported Content (1st run):")
    if os.path.exists(out_file):
        with open(out_file, "r", encoding="utf-8") as f:
            print(f.read())
        
    print("Testing duplicates avoidance (2nd run):")
    svc.run(log_path, out_file)
    if os.path.exists(out_file):
        with open(out_file, "r", encoding="utf-8") as f:
            print(f.read())

if __name__ == "__main__":
    test_headless()
