import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

SETTINGS_FILE = 'settings.json'

@dataclass
class AppSettings:
    log_file_path: str = ""
    output_folder_path: str = ""
    mode: str = "import" # "import" or "monitor"
    append_description: bool = False
    avoid_duplicates: bool = True
    min_tracks: Optional[int] = None
    min_duration: Optional[int] = None
    custom_filename: str = ""
    add_filter_info: bool = False
    last_export_timestamp: str = ""
    filter_by_timestamp: bool = False

class SettingsManager:
    @staticmethod
    def load() -> AppSettings:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return AppSettings(**data)
            except Exception as e:
                print(f"Failed to load settings: {e}")
        return AppSettings()

    @staticmethod
    def save(settings: AppSettings):
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(asdict(settings), f, indent=4)
        except Exception as e:
            print(f"Failed to save settings: {e}")
