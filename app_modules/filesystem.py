import os
import sys
from datetime import datetime, timezone
from typing import List

from app_modules.debug_logging import emit_debug


def _filesystem_debug(message: str) -> None:
    emit_debug("filesystem", message)


def list_directory_entries(path: str) -> List[dict]:
    _filesystem_debug(f"Listing directory entries for `{path}`.")
    if not os.path.isdir(path):
        _filesystem_debug("Path is not a directory; returning empty list.")
        return []

    entries: List[dict] = []
    try:
        with os.scandir(path) as scan:
            for entry in scan:
                name = entry.name
                if name.startswith("."):
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                stat_info = entry.stat(follow_symlinks=False)
                entries.append(
                    {
                        "name": name,
                        "path": entry.path,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else int(stat_info.st_size),
                        "modified": datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    }
                )
    except Exception as e:
        _filesystem_debug(f"Error while scanning directory `{path}`: {e}")
        return []

    entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
    _filesystem_debug(f"Found {len(entries)} visible entries in `{path}`.")
    return entries
