from core.settings import AppSettings
from core.service import ImportService
import os

def test_dry_run():
    settings = AppSettings(
        log_file_path="test_log.txt",
        output_folder_path=".",
        avoid_duplicates=True,
        min_tracks=0,
        min_duration=0,
        filter_by_timestamp=True,
        last_export_timestamp="10:21:00"
    )

    def dummy_callback(msg):
        print("UI Update:", msg)

    srv = ImportService(settings, dummy_callback)
    
    print("Testing dry run...")
    # Clean export_test to pretend we have no existing urls
    if os.path.exists("test_out.txt"):
        os.remove("test_out.txt")
        
    srv.dry_run("test_log.txt", "test_out.txt")
    print("\nTesting actual run...")
    srv.run("test_log.txt", "test_out.txt")

if __name__ == "__main__":
    test_dry_run()
