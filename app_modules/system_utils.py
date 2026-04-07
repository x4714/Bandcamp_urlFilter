import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from app_modules.debug_logging import emit_debug


def _system_utils_debug(message: str) -> None:
    emit_debug("system utils", message)


def open_in_default_app(path: str) -> None:
    target = os.path.abspath(path)
    _system_utils_debug(f"Opening path in default app: `{target}`.")
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
        _system_utils_debug("Used Windows os.startfile opener.")
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
        _system_utils_debug("Used macOS `open` command.")
        return

    opener = shutil.which("xdg-open")
    if not opener:
        _system_utils_debug("Could not find xdg-open on this system.")
        raise RuntimeError("Could not find xdg-open to launch files/folders.")
    subprocess.Popen([opener, target])
    _system_utils_debug(f"Used Linux opener `{opener}`.")
