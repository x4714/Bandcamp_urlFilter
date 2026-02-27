import sys
import os

# Add the parent directory to sys.path so we can import 'core'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.settings import AppSettings
from core.service import ImportService

def test_dry_run():
    log_path = os.path.join(os.path.dirname(__file__), "..", "test_log.txt")
    
    settings = AppSettings(
        log_file_path=log_path,
        output_folder_path=".",
        avoid_duplicates=True,
        min_tracks=0,
        min_duration=0,
        filter_by_timestamp=True,
        last_export_timestamp="10:21:00"
    )

    if not os.path.exists(log_path):
        print(f"Error: test_log.txt not found at {log_path}")
        return

    def dummy_callback(msg):
        print("UI Update:", msg)

    srv = ImportService(settings, dummy_callback)
    
    print("Testing dry run...")
    test_out = "test_out.txt"
    if os.path.exists(test_out):
        os.remove(test_out)
        
    srv.dry_run(log_path, test_out)
    print("\nTesting actual run...")
    srv.run(log_path, test_out)

if __name__ == "__main__":
    test_dry_run()
