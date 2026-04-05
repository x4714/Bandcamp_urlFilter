import streamlit as st

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


def init_session_state() -> None:
    for key, default_value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default_value
