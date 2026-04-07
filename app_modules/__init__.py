"""Application modules for the Streamlit app."""

from datetime import datetime, timezone
import sys

from app_modules.debug_logging import emit_debug


def _app_modules_debug(message: str) -> None:
    emit_debug("app modules", message)
