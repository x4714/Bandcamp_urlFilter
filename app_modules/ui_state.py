import sys
import copy
from datetime import datetime, timezone

import streamlit as st
from app_modules.debug_logging import emit_debug

SESSION_DEFAULTS = {
    "results": [],
    "process_complete": False,
    "export_done": False,
    "cancel_requested": False,
    "processing": False,
    "pending_entries": [],
    "current_index": 0,
    "total_entries": 0,
    "status_log": "",
    "is_dry_run_run": False,
    "dry_run_results": [],
    "rip_last_level": "",
    "rip_last_message": "",
    "rip_last_log_path": "",
    "direct_rip_last_level": "",
    "direct_rip_last_message": "",
    "direct_rip_last_log_path": "",
    "salmon_last_level": "",
    "salmon_last_message": "",
    "salmon_last_log_path": "",
}

# Keys that should survive Streamlit session_state recreation when available
# from the process snapshot store, but should not be initialized on first run.
SESSION_SNAPSHOT_ONLY_KEYS = [
    "streamrip_runtime_state",
    "direct_qobuz_paste_text",
    "main_tab_selection",
    "wip_matcher",
    "wip_direct_rip",
    "wip_smoked_salmon",
    "streamrip_downloads_folder_persist",
    "streamrip_downloads_folder_draft",
    "streamrip_browser_path",
    "streamrip_nav_back",
    "streamrip_nav_forward",
    "streamrip_browser_entries_cache_path",
    "streamrip_browser_entries_cache_data",
    "streamrip_browser_entries_cache_ts",
    "streamrip_browser_entries_refresh_requested",
    "qobuz_account_info_cache",
    "qobuz_env_token_sync_marker",
    "qobuz_autofill_notice",
]


def _ui_state_debug(message: str) -> None:
    emit_debug("ui state", message)


def _clone_session_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return copy.deepcopy(value)


@st.cache_resource(show_spinner=False)
def _get_session_defaults_snapshot_store() -> dict[str, object]:
    # Process-level fallback to rehydrate key UI state when Streamlit recreates session_state.
    return {}


def remember_session_snapshot_value(key: str, value: object) -> None:
    snapshot_store = _get_session_defaults_snapshot_store()
    snapshot_store[str(key)] = _clone_session_value(value)


def init_session_state() -> None:
    snapshot_store = _get_session_defaults_snapshot_store()
    initialized_count = 0
    restored_count = 0
    for key, default_value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            if key in snapshot_store:
                st.session_state[key] = _clone_session_value(snapshot_store[key])
                restored_count += 1
            else:
                st.session_state[key] = _clone_session_value(default_value)
            initialized_count += 1
    for key in SESSION_SNAPSHOT_ONLY_KEYS:
        if key not in st.session_state and key in snapshot_store:
            st.session_state[key] = _clone_session_value(snapshot_store[key])
            restored_count += 1
    for key in SESSION_DEFAULTS:
        snapshot_store[key] = _clone_session_value(st.session_state.get(key))
    for key in SESSION_SNAPSHOT_ONLY_KEYS:
        if key in st.session_state:
            snapshot_store[key] = _clone_session_value(st.session_state.get(key))
    _ui_state_debug(
        "Session state init complete. "
        f"initialized={initialized_count}, restored_from_snapshot={restored_count}, "
        f"total_defaults={len(SESSION_DEFAULTS)}."
    )
