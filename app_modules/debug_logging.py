import os
import sys
import threading
from datetime import datetime, timezone

_DEBUG_LOCK = threading.Lock()
_DEBUG_DIR = os.path.abspath(".debug")
_DEBUG_LOG_PATH = os.path.join(_DEBUG_DIR, "app_debug.log")
_DEBUG_LOG_PREFIX = "app_debug_"
_DEBUG_LOG_SUFFIX = ".log"
_DEBUG_LOG_MAX_BYTES_DEFAULT = 5 * 1024 * 1024
_DEBUG_LOG_MAX_FILES_DEFAULT = 10
_DEBUG_LOG_MIN_BYTES = 64 * 1024
_LOGGER_INITIALIZED = False


def _get_debug_log_max_bytes() -> int:
    raw = os.getenv("APP_DEBUG_LOG_MAX_BYTES", "").strip()
    if not raw:
        return _DEBUG_LOG_MAX_BYTES_DEFAULT
    try:
        parsed = int(raw)
        return max(_DEBUG_LOG_MIN_BYTES, parsed)
    except ValueError:
        return _DEBUG_LOG_MAX_BYTES_DEFAULT


def _get_debug_log_max_files() -> int:
    raw = os.getenv("APP_DEBUG_LOG_MAX_FILES", "").strip()
    if not raw:
        return _DEBUG_LOG_MAX_FILES_DEFAULT
    try:
        parsed = int(raw)
        return max(1, parsed)
    except ValueError:
        return _DEBUG_LOG_MAX_FILES_DEFAULT


def _archive_name_from_now() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return os.path.join(_DEBUG_DIR, f"{_DEBUG_LOG_PREFIX}{stamp}_pid{os.getpid()}{_DEBUG_LOG_SUFFIX}")


def _list_archived_logs() -> list[str]:
    files: list[str] = []
    try:
        for name in os.listdir(_DEBUG_DIR):
            if not name.startswith(_DEBUG_LOG_PREFIX) or not name.endswith(_DEBUG_LOG_SUFFIX):
                continue
            files.append(os.path.join(_DEBUG_DIR, name))
    except Exception:
        return []
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files


def _enforce_max_log_files(max_files: int) -> None:
    # `max_files` includes the current app_debug.log.
    max_archived = max(0, max_files - 1)
    archived = _list_archived_logs()
    for stale_path in archived[max_archived:]:
        try:
            os.remove(stale_path)
        except Exception:
            pass


def _initialize_logger() -> None:
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    os.makedirs(_DEBUG_DIR, exist_ok=True)
    if os.path.isfile(_DEBUG_LOG_PATH) and os.path.getsize(_DEBUG_LOG_PATH) > 0:
        archive_path = _archive_name_from_now()
        try:
            os.replace(_DEBUG_LOG_PATH, archive_path)
        except Exception:
            pass

    with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
        started_at = datetime.now(timezone.utc).isoformat()
        f.write(f"[debug log start] {started_at} pid={os.getpid()}\n")

    _enforce_max_log_files(_get_debug_log_max_files())
    _LOGGER_INITIALIZED = True


def _trim_debug_log_if_needed(log_path: str, max_bytes: int) -> None:
    if max_bytes <= 0 or not os.path.isfile(log_path):
        return
    current_size = os.path.getsize(log_path)
    if current_size <= max_bytes:
        return

    keep_bytes = max(max_bytes // 2, _DEBUG_LOG_MIN_BYTES)
    with open(log_path, "rb") as src:
        if current_size > keep_bytes:
            src.seek(-keep_bytes, os.SEEK_END)
        tail = src.read()

    newline_pos = tail.find(b"\n")
    if newline_pos != -1 and newline_pos + 1 < len(tail):
        tail = tail[newline_pos + 1 :]

    with open(log_path, "wb") as dst:
        dst.write(b"[debug log rotated]\n")
        dst.write(tail)


def emit_debug(channel: str, message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    rendered = f"[{channel} debug {timestamp} UTC] {message}"
    print(rendered, file=sys.stderr, flush=True)
    try:
        with _DEBUG_LOCK:
            _initialize_logger()
            _trim_debug_log_if_needed(_DEBUG_LOG_PATH, _get_debug_log_max_bytes())
            with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(rendered + "\n")
    except Exception:
        # Debug logging must never break app execution.
        pass
