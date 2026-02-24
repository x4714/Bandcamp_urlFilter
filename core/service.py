import os
import time
from typing import Callable, Set, TextIO, Optional
from core.settings import AppSettings
from core.parser import parse_line
from core.filter import LogFilter

class BaseService:
    def __init__(self, settings: AppSettings, update_callback: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.update_callback = update_callback or (lambda msg: None)
        self.log_filter = LogFilter(settings)
        self.is_running = False

    def get_existing_urls(self, filepath: str) -> Set[str]:
        """Reads the output file to populate existing URLs to avoid duplicates."""
        existing = set()
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    # Line format could be just URL or URL | Meta
                    url = line.split('|')[0].strip()
                    if url:
                        existing.add(url)
        return existing

    def process_and_write_line(self, line: str, out_file: TextIO, seen_urls: Set[str]) -> bool:
        """Parses, filters and writes line to file if matched. Returns True if written."""
        entry = parse_line(line)
        if entry and self.log_filter.is_valid(entry):
            if self.settings.avoid_duplicates and entry.url in seen_urls:
                return False

            output_line = entry.url
            if self.settings.append_description and entry.meta_raw:
                output_line += f" | {entry.meta_raw}"
            
            out_file.write(output_line + '\n')
            out_file.flush()
            seen_urls.add(entry.url)
            return True
        return False

class ImportService(BaseService):
    def run(self, input_path: str, output_path: str):
        self.is_running = True
        self.update_callback("Starting Import...")
        
        if not os.path.exists(input_path):
            self.update_callback(f"Error: Log file not found at {input_path}")
            self.is_running = False
            return

        seen_urls = self.get_existing_urls(output_path)
        added_count = 0

        try:
            with open(input_path, 'r', encoding='utf-8', errors='ignore') as infile, \
                 open(output_path, 'a', encoding='utf-8') as outfile:
                
                for line in infile:
                    if not self.is_running:
                        self.update_callback("Import stopped by user.")
                        break
                        
                    if self.process_and_write_line(line, outfile, seen_urls):
                        added_count += 1

            if self.is_running:
                self.update_callback(f"Import complete. Added {added_count} new entries.")
        except Exception as e:
            self.update_callback(f"Import error: {e}")
        finally:
            self.is_running = False

    def stop(self):
        self.is_running = False

class MonitorService(BaseService):
    def run(self, input_path: str, output_path: str):
        self.is_running = True
        self.update_callback("Starting Monitor...")

        if not os.path.exists(input_path):
            self.update_callback(f"Error: Log file not found at {input_path}")
            self.is_running = False
            return

        seen_urls = self.get_existing_urls(output_path)
        added_count = 0

        try:
            with open(input_path, 'r', encoding='utf-8', errors='ignore') as infile, \
                 open(output_path, 'a', encoding='utf-8') as outfile:
                
                # Go to the end of the file
                infile.seek(0, 2)
                
                self.update_callback("Monitoring for new entries...")
                while self.is_running:
                    line = infile.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    
                    if self.process_and_write_line(line, outfile, seen_urls):
                        added_count += 1
                        self.update_callback(f"Monitor active. Added {added_count} new entries so far.")

        except Exception as e:
            self.update_callback(f"Monitor error: {e}")
        finally:
            self.is_running = False
            self.update_callback("Monitor stopped.")

    def stop(self):
        self.is_running = False
