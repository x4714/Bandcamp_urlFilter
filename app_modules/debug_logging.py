import logging
import os
import re
import threading
import time
from logging.handlers import RotatingFileHandler


_DEBUG_DIR = os.path.abspath(".debug")
_DEBUG_LOG_PATH = os.path.join(_DEBUG_DIR, "app_debug.log")
_DEBUG_LOG_MAX_BYTES_DEFAULT = 5 * 1024 * 1024
_DEBUG_LOG_MAX_FILES_DEFAULT = 10
_DEBUG_LOG_MIN_BYTES = 64 * 1024
_DEBUG_LOGGER_NAME = "bandcamp_urlfilter.debug"
_LOGGER_INIT_LOCK = threading.Lock()
_LOGGER_INITIALIZED = False

_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(x-user-auth-token|authorization)\b([=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)\b(qobuz_user_auth_token|app_auth_password_hash|red_api_key|ops_api_key)\b([=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)\b(password_or_token|app_auth_token|cookie_value)\b([=:]\s*)([^\s,;]+)"),
]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


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


def _sanitize_debug_text(message: str) -> str:
    sanitized = str(message or "")
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", sanitized)
    return sanitized


def _configure_debug_logger() -> logging.Logger:
    global _LOGGER_INITIALIZED
    logger = logging.getLogger(_DEBUG_LOGGER_NAME)
    if _LOGGER_INITIALIZED:
        return logger

    with _LOGGER_INIT_LOCK:
        if _LOGGER_INITIALIZED:
            return logger

        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        formatter = logging.Formatter(
            "[%(name)s %(levelname)s %(asctime)s UTC] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        formatter.converter = time.gmtime  # type: ignore[name-defined]

        if _env_flag("APP_DEBUG_STDERR", default=False):
            stderr_handler = logging.StreamHandler()
            stderr_handler.setLevel(logging.DEBUG)
            stderr_handler.setFormatter(formatter)
            logger.addHandler(stderr_handler)

        if _env_flag("APP_DEBUG_LOG_ENABLED", default=False):
            os.makedirs(_DEBUG_DIR, exist_ok=True)
            file_handler = RotatingFileHandler(
                _DEBUG_LOG_PATH,
                maxBytes=_get_debug_log_max_bytes(),
                backupCount=max(0, _get_debug_log_max_files() - 1),
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        _LOGGER_INITIALIZED = True
    return logger


def emit_debug(channel: str, message: str) -> None:
    logger = _configure_debug_logger()
    if not logger.handlers:
        return
    try:
        logger.debug("[%s] %s", str(channel or "app").strip(), _sanitize_debug_text(message))
    except Exception:
        pass
