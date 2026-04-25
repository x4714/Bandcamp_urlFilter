from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv
from app_modules.app_auth import render_auth_gate
from app_modules.debug_logging import emit_debug

from app_modules.filtering import validate_filters
from app_modules.streamrip import (
    CODEC_OPTIONS,
    QUALITY_OPTIONS,
    ensure_streamrip_config_file,
    fetch_qobuz_account_info,
    get_default_downloads_folder,
    get_env_qobuz_values,
    get_streamrip_config_path,
    is_streamrip_installed,
    load_streamrip_settings,
    save_streamrip_settings,
    update_streamrip_quality_only,
)
from app_modules.system_utils import open_in_default_app
from app_modules.qobuz_utils import _token_fingerprint
from app_modules.ui_processing import (
    handle_process_submission,
    render_results_and_exports,
    render_status_log,
    run_processing_tick,
)
from app_modules.ui_modal import (
    close_qobuz_help_modal,
    init_qobuz_help_state,
    render_modal_base_styles,
)
from app_modules.ui_qobuz_settings import (
    _pick_streamrip_identifier_from_account,
    render_qobuz_settings_tab,
)
from app_modules.ui_smoked_salmon import render_smoked_salmon_tab
from app_modules.ui_state import init_session_state, remember_session_snapshot_value
from app_modules.ui_js import run_inline_script
from app_modules.ui_streamrip_setup import (
    init_streamrip_download_state,
    init_streamrip_form_state,
)
from app_modules.ui_streamrip_settings import render_streamrip_settings_tab
from app_modules.ui_tools import render_direct_qobuz_rip_tab

ENV_FILE_PATH = ".env"
ENV_TEMPLATE_PATH = ".env.example"

MAIN_TABS = [
    "Bandcamp Matcher",
    "Direct Qobuz Rip",
    "Smoked Salmon Upload",
    "Smoked Salmon Settings",
    "Qobuz Settings",
    "Streamrip Settings",
]


def _app_debug(message: str) -> None:
    emit_debug("app", message)


def render_wip_notice() -> None:
    st.markdown(
        f"""
        <div style="
            margin: 0.4rem 0 1rem 0;
            padding: 0.9rem 1rem;
            border-radius: 10px;
            border: 1px solid rgba(128,128,128,0.25);
            background: linear-gradient(135deg, rgba(255,191,71,0.14), rgba(80,140,255,0.08));
            color: inherit;
            font-weight: 600;
            font-size: 3rem;
            text-align: center;
            letter-spacing: 0.2px;
        ">
            WIP 🚧
        </div>
        """,
        unsafe_allow_html=True,
    )


def _build_streamrip_rip_disabled_reason(
    installed: bool,
    config_ready: bool,
    config_init_msg: str,
    settings_error: str,
    missing_required_fields: list[str],
) -> str:
    if installed is False:
        return "Streamrip module is missing."

    settings_error_text = str(settings_error or "").strip()
    if settings_error_text:
        return settings_error_text

    if not config_ready:
        return str(config_init_msg or "Streamrip config is not ready yet.").strip()

    if missing_required_fields:
        missing_labels = {
            "email_or_userid": "Qobuz Email or User ID",
            "password_or_token": "Qobuz Password Hash or Auth Token",
            "downloads_folder": "Downloads Folder Path",
            "downloads_db_path": "Downloads DB Path",
            "failed_downloads_path": "Failed Downloads Folder Path",
        }
        labels = [missing_labels.get(f, f.replace("_", " ").title()) for f in missing_required_fields]
        return "Missing Streamrip settings: " + ", ".join(labels)

    return ""


def _get_file_mtime_ns(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


def _sync_env_file_changes() -> None:
    current_mtime_ns = _get_file_mtime_ns(ENV_FILE_PATH)
    previous_mtime_ns = st.session_state.get("_env_file_mtime_ns")
    if previous_mtime_ns is None:
        st.session_state["_env_file_mtime_ns"] = current_mtime_ns
        return
    if current_mtime_ns != previous_mtime_ns:
        st.session_state["_env_file_mtime_ns"] = current_mtime_ns
        load_dotenv(override=True)
        _app_debug("Detected .env file change; reloaded environment values.")


def _mount_env_watchdog() -> None:
    # Keep env sync deterministic and avoid background fragment rerun churn.
    _sync_env_file_changes()


def _render_alert_scroll_if_requested() -> None:
    if not st.session_state.get("auto_scroll_alerts_once", False):
        return
    run_inline_script(
        """
        <script>
            const doc = window.parent.document;
            const alerts = doc.querySelectorAll('[data-testid="stAlert"]');
            if (alerts.length > 0) {
                alerts[0].scrollIntoView({ behavior: "smooth", block: "center" });
            } else {
                const root = doc.querySelector("section.main");
                if (root) {
                    root.scrollTo({ top: 0, behavior: "smooth" });
                } else {
                    window.parent.scrollTo({ top: 0, behavior: "smooth" });
                }
            }
        </script>
        """,
        height=1,
    )
    st.session_state["auto_scroll_alerts_once"] = False


def _on_rip_quality_change() -> None:
    quality = st.session_state.get("streamrip_runtime_rip_quality")
    if quality is None or quality not in QUALITY_OPTIONS:
        return
    st.session_state["active_rip_quality"] = quality
    config_path = get_streamrip_config_path()
    if config_path and os.path.exists(config_path):
        ok, msg = update_streamrip_quality_only(config_path, quality)
        if ok:
            st.session_state["streamrip_form_quality"] = quality
        st.session_state["_quality_save_result"] = (ok, msg)


def _apply_pending_main_tab_redirect() -> None:
    pending_target = str(st.session_state.pop("main_tab_selection_pending", "")).strip()
    if pending_target and pending_target in MAIN_TABS:
        st.session_state["main_tab_selection"] = pending_target

def _configure_page_shell() -> None:
    load_dotenv()
    st.set_page_config(page_title="Bandcamp to Qobuz Matcher", layout="wide")
    render_auth_gate()
    st.title("🎵 Bandcamp to Qobuz Matcher")
    st.markdown("Filter your Bandcamp URLs and find exact high-resolution matches on Qobuz.")
    render_modal_base_styles()


def _render_main_tab_selector() -> str:
    st.markdown(
        """
<style>
.st-key-main_tab_selection [data-testid="stRadio"] > div {
  display: flex;
  gap: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.16);
}
.st-key-main_tab_selection [data-baseweb="radio"] {
  margin-right: 0 !important;
  padding: 0.55rem 0.9rem 0.6rem 0.9rem;
  border-bottom: 2px solid transparent;
}
.st-key-main_tab_selection [data-baseweb="radio"] > div:first-child {
  display: none;
}
.st-key-main_tab_selection [data-baseweb="radio"] > div:last-child {
  font-weight: 600;
  opacity: 0.82;
}
.st-key-main_tab_selection [data-baseweb="radio"]:has(input:checked) {
  border-bottom-color: #ff4b4b !important;
}
.st-key-main_tab_selection [data-baseweb="radio"]:has(input:checked) > div:last-child {
  opacity: 1;
  color: inherit !important;
}
</style>
""",
        unsafe_allow_html=True,
    )
    _apply_pending_main_tab_redirect()
    main_tab = st.radio(
        "Main Tab",
        options=MAIN_TABS,
        key="main_tab_selection",
        horizontal=True,
        label_visibility="collapsed",
    )
    _app_debug(f"Main tab selected: `{main_tab}`.")
    if main_tab != "Qobuz Settings" and (
        st.session_state.get("qobuz_token_help_passphrase_open")
        or st.session_state.get("qobuz_token_help_content_open")
    ):
        _app_debug("Closing Qobuz help modal because the active tab is no longer Qobuz Settings.")
        close_qobuz_help_modal(clear_text=False)
    return main_tab


def _default_sidebar_values() -> dict:
    return {
        "tag_input": "",
        "exclude_tag_input": "",
        "location_input": "",
        "min_tracks": None,
        "max_tracks": None,
        "min_duration": None,
        "max_duration": None,
        "start_date": None,
        "end_date": None,
        "free_mode": "All",
        "only_24bit": False,
        "dry_run": False,
        "ui_concurrency": 2,
        "ui_request_delay": 1.0,
        "ui_qobuz_retries": 3,
        "ui_qobuz_retry_delay": 10.0,
        "ui_bc_retries": 5,
        "ui_bc_retry_delay": 10.0,
        "check_red": False,
        "check_ops": False,
    }

def _open_env_for_qobuz() -> None:
    env_path = ENV_FILE_PATH
    if not os.path.exists(env_path):
        try:
            if os.path.exists(ENV_TEMPLATE_PATH):
                shutil.copyfile(ENV_TEMPLATE_PATH, env_path)
            else:
                with open(env_path, "w", encoding="utf-8") as env_file:
                    env_file.write("PYTHONPATH=.\nQOBUZ_USER_AUTH_TOKEN=\n")
        except Exception as e:
            _app_debug(f"Failed creating .env template file: {e}")
            st.session_state["auto_scroll_alerts_once"] = True
            st.error(f"Error creating the .env file: {e}")
            return

    try:
        open_in_default_app(env_path)
        _app_debug("Opened .env in default app.")
    except Exception as e:
        _app_debug(f"Failed opening .env in default app: {e}")
        st.session_state["auto_scroll_alerts_once"] = True
        st.error(f"Could not open .env: {e}")


def _render_sidebar_controls(main_tab: str) -> dict:
    sidebar_values = _default_sidebar_values()

    if main_tab == "Bandcamp Matcher":
        st.sidebar.header("Configuration")
        _app_debug("Sidebar: Configuration header rendered.")
        _app_debug("Sidebar: rendering matcher filter/date/run settings.")
        with st.sidebar.expander("🎯 Matcher Filter Rules", expanded=False):
            sidebar_values["tag_input"] = st.text_input("Include Genre / Tag", value="", help="Filter by tag or genre. Separate multiple with commas (e.g. 'rock, jazz').")
            sidebar_values["exclude_tag_input"] = st.text_input("Exclude Genre / Tag", value="", help="Exclude tags or genres. Separate multiple with commas.")
            sidebar_values["location_input"] = st.text_input("Location", value="", help="Filter by location text in metadata.")
            sidebar_values["min_tracks"] = st.number_input("Min Tracks", min_value=1, value=None, step=1, help="Leave empty for no minimum.")
            sidebar_values["max_tracks"] = st.number_input("Max Tracks", min_value=1, value=None, step=1, help="Leave empty for no maximum.")
            sidebar_values["min_duration"] = st.number_input("Min Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no minimum.")
            sidebar_values["max_duration"] = st.number_input("Max Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no maximum.")

        with st.sidebar.expander("📅 Matcher Release Date Filter", expanded=False):
            sidebar_values["start_date"] = st.date_input("Start Date", value=None, help="Filter for releases on or after this date.")
            sidebar_values["end_date"] = st.date_input("End Date", value=None, help="Filter for releases on or before this date.")

        with st.sidebar.expander("⚙️ Matcher Run Settings", expanded=True):
            sidebar_values["free_mode"] = st.selectbox("Pricing", options=["All", "Free", "Paid"], index=0, help="Filter releases by Bandcamp pricing type.")
            sidebar_values["only_24bit"] = st.toggle("Only 24-bit", value=False, help="Only collect albums available in 24-bit hi-res on Qobuz.")
            sidebar_values["dry_run"] = st.checkbox("Dry Run", value=False, help="Only apply Bandcamp filter, skip Qobuz search.")
            red_key = os.getenv("RED_API_KEY", "")
            ops_key = os.getenv("OPS_API_KEY", "")
            if red_key:
                sidebar_values["check_red"] = st.checkbox("Check RED", value=False, help="Check Qobuz matches against Redacted (RED) for duplicates.")
            if ops_key:
                sidebar_values["check_ops"] = st.checkbox("Check OPS", value=False, help="Check Qobuz matches against Orpheus (OPS) for duplicates.")

        with st.sidebar.expander("⏱️ Rate Limits & Retries", expanded=False):
            sidebar_values["ui_concurrency"] = st.number_input(
                "Concurrency",
                min_value=1, max_value=10, value=2, step=1,
                help="Number of Bandcamp/Qobuz requests to run in parallel.",
            )
            sidebar_values["ui_request_delay"] = st.number_input(
                "Request Delay (s)",
                min_value=0.0, max_value=30.0, value=1.0, step=0.5, format="%.1f",
                help="Minimum seconds between requests to the same host.",
            )
            sidebar_values["ui_qobuz_retries"] = st.number_input(
                "Qobuz Retries",
                min_value=1, max_value=10, value=3, step=1,
                help="Max retry attempts on Qobuz 429 / 5xx errors.",
            )
            sidebar_values["ui_qobuz_retry_delay"] = st.number_input(
                "Qobuz Retry Base Delay (s)",
                min_value=0.5, max_value=60.0, value=10.0, step=0.5, format="%.1f",
                help="Base delay for exponential back-off on Qobuz retries (doubles each attempt).",
            )
            sidebar_values["ui_bc_retries"] = st.number_input(
                "Bandcamp Retries",
                min_value=1, max_value=15, value=5, step=1,
                help="Max retry attempts on Bandcamp 429 / 5xx errors.",
            )
            sidebar_values["ui_bc_retry_delay"] = st.number_input(
                "Bandcamp Retry Base Delay (s)",
                min_value=0.5, max_value=60.0, value=10.0, step=0.5, format="%.1f",
                help="Base delay for exponential back-off on Bandcamp retries (doubles each attempt, plus jitter).",
            )

    if main_tab in {"Qobuz Settings", "Streamrip Settings", "Smoked Salmon Settings"}:
        st.sidebar.header("Configuration")
        _app_debug("Sidebar: Configuration header rendered for settings tab.")

        with st.sidebar.expander("🛠️ Tracker Debugger", expanded=False):
            st.caption("Manually test duplicate checks for RED/OPS.")
            dbg_artist = st.text_input("Test Artist", key="dbg_art")
            dbg_album = st.text_input("Test Album", key="dbg_alb")
            dbg_upc = st.text_input("Test UPC (Optional)", key="dbg_upc")

            if st.button("Run Diagnostic Check", use_container_width=True):
                if not dbg_artist or not dbg_album:
                    st.warning("Please enter at least Artist and Album.")
                else:
                    from app_modules.ui_processing import run_tracker_diagnostic

                    run_tracker_diagnostic(dbg_artist, dbg_album, dbg_upc)

    return sidebar_values

def _load_streamrip_runtime_state(
    status_callback=None,
) -> tuple[str, bool, str, dict, str, str, str]:
    _app_debug("Loading streamrip runtime state.")
    if status_callback:
        status_callback("Resolving Streamrip config path...")
    config_path = get_streamrip_config_path()

    if status_callback:
        status_callback("Checking Streamrip config file...")
    config_ready, config_init_msg = ensure_streamrip_config_file(config_path)

    settings = {}
    settings_error = ""
    if config_ready:
        if status_callback:
            status_callback("Loading Streamrip settings from config.toml...")
        settings, settings_error = load_streamrip_settings(config_path)

    if status_callback:
        status_callback("Reading .env and resolving Qobuz token/App ID...")
    qobuz_app_id, qobuz_token = get_env_qobuz_values(
        status_callback=status_callback,
        fallback_app_id=str(settings.get("app_id", "")).strip(),
    )
    _app_debug(
        "Streamrip runtime state loaded "
        f"(config_ready={config_ready}, settings_loaded={bool(settings)}, "
        f"app_id_present={bool(qobuz_app_id)}, token_present={bool(qobuz_token)})."
    )
    return (
        config_path,
        config_ready,
        config_init_msg,
        settings,
        settings_error,
        qobuz_app_id,
        qobuz_token,
    )


def _make_streamrip_boot_status_callback(streamrip_boot_status):
    # Throttle very chatty discovery updates so the status label stays readable.
    last = {"message": "", "emit_at": 0.0}

    def _update(message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        now = time.monotonic()
        if text == last["message"] and (now - float(last["emit_at"])) < 1.0:
            return
        if (now - float(last["emit_at"])) < 0.2:
            return
        last["message"] = text
        last["emit_at"] = now
        streamrip_boot_status.update(label=f"Streamrip setup: {text}", state="running")

    return _update


@st.cache_data(show_spinner=False)
def _load_streamrip_runtime_state_cached(
    env_mtime_ns: int,
    config_path_hint: str,
    config_mtime_ns: int,
    _status_callback=None,
) -> tuple[str, bool, str, dict, str, str, str]:
    # Cache key is fully represented by function args; values are intentionally unused.
    _ = (env_mtime_ns, config_path_hint, config_mtime_ns)
    _app_debug("Loading streamrip runtime state via process cache.")
    return _load_streamrip_runtime_state(status_callback=_status_callback)


_STREAMRIP_RUNTIME_SNAPSHOT_KEY_SESSION_KEY = "_streamrip_runtime_snapshot_key"
_STREAMRIP_RUNTIME_SNAPSHOT_STATE_SESSION_KEY = "_streamrip_runtime_snapshot_state"


@st.cache_resource
def _streamrip_config_path_hint_store() -> dict:
    # Process-global warm hint for the next cold boot.
    return {"config_path_hint": ""}


def _snapshot_streamrip_runtime_state(
    env_mtime_ns: int,
    config_mtime_ns: int,
    state: tuple[str, bool, str, dict, str, str, str],
) -> None:
    st.session_state[_STREAMRIP_RUNTIME_SNAPSHOT_KEY_SESSION_KEY] = (int(env_mtime_ns), int(config_mtime_ns))
    st.session_state[_STREAMRIP_RUNTIME_SNAPSHOT_STATE_SESSION_KEY] = state

    store = _streamrip_config_path_hint_store()
    store["config_path_hint"] = str(state[0] or "")


def _read_streamrip_runtime_snapshot(
    env_mtime_ns: int,
    config_mtime_ns: int,
) -> tuple[str, bool, str, dict, str, str, str] | None:
    snapshot_key = st.session_state.get(_STREAMRIP_RUNTIME_SNAPSHOT_KEY_SESSION_KEY)
    if snapshot_key != (int(env_mtime_ns), int(config_mtime_ns)):
        return None
    state = st.session_state.get(_STREAMRIP_RUNTIME_SNAPSHOT_STATE_SESSION_KEY)
    if isinstance(state, tuple) and len(state) == 7:
        return state
    return None


def _get_streamrip_config_path_hint() -> str:
    store = _streamrip_config_path_hint_store()
    hint = str(store.get("config_path_hint", "")).strip()
    return hint


def _cache_streamrip_runtime_state(
    config_path: str,
    config_ready: bool,
    config_init_msg: str,
    settings: dict,
    settings_error: str,
    qobuz_app_id: str,
    qobuz_token: str,
) -> None:
    st.session_state.streamrip_runtime_state = {
        "config_path": config_path,
        "config_ready": bool(config_ready),
        "config_init_msg": str(config_init_msg or ""),
        "settings": dict(settings or {}),
        "settings_error": str(settings_error or ""),
        "qobuz_app_id": str(qobuz_app_id or ""),
        "qobuz_token": str(qobuz_token or ""),
        "env_mtime_ns": _get_file_mtime_ns(ENV_FILE_PATH),
        "config_mtime_ns": _get_file_mtime_ns(config_path),
    }
    remember_session_snapshot_value("streamrip_runtime_state", st.session_state.streamrip_runtime_state)
    _snapshot_streamrip_runtime_state(
        st.session_state.streamrip_runtime_state["env_mtime_ns"],
        st.session_state.streamrip_runtime_state["config_mtime_ns"],
        (
            config_path,
            bool(config_ready),
            str(config_init_msg or ""),
            dict(settings or {}),
            str(settings_error or ""),
            str(qobuz_app_id or ""),
            str(qobuz_token or ""),
        ),
    )


def _streamrip_runtime_cache_is_stale(cache: dict) -> bool:
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    config_path = str(cache.get("config_path", "")).strip()
    if not config_path:
        return True
    current_env_mtime = _get_file_mtime_ns(ENV_FILE_PATH)
    current_config_mtime = _get_file_mtime_ns(config_path)
    cached_env_mtime = _safe_int(cache.get("env_mtime_ns", -2), -2)
    cached_config_mtime = _safe_int(cache.get("config_mtime_ns", -2), -2)
    return (cached_env_mtime != current_env_mtime) or (cached_config_mtime != current_config_mtime)


def main() -> None:
    _configure_page_shell()
    init_session_state()
    init_qobuz_help_state()
    _mount_env_watchdog()

    main_tab = _render_main_tab_selector()
    sidebar_values = _render_sidebar_controls(main_tab)

    tag_input = sidebar_values["tag_input"]
    exclude_tag_input = sidebar_values["exclude_tag_input"]
    location_input = sidebar_values["location_input"]
    min_tracks = sidebar_values["min_tracks"]
    max_tracks = sidebar_values["max_tracks"]
    min_duration = sidebar_values["min_duration"]
    max_duration = sidebar_values["max_duration"]
    start_date = sidebar_values["start_date"]
    end_date = sidebar_values["end_date"]
    free_mode = sidebar_values["free_mode"]
    only_24bit = sidebar_values["only_24bit"]
    dry_run = sidebar_values["dry_run"]
    ui_concurrency = sidebar_values["ui_concurrency"]
    ui_request_delay = sidebar_values["ui_request_delay"]
    ui_qobuz_retries = sidebar_values["ui_qobuz_retries"]
    ui_qobuz_retry_delay = sidebar_values["ui_qobuz_retry_delay"]
    ui_bc_retries = sidebar_values["ui_bc_retries"]
    ui_bc_retry_delay = sidebar_values["ui_bc_retry_delay"]
    check_red = sidebar_values["check_red"]
    check_ops = sidebar_values["check_ops"]

    cached_streamrip_state = st.session_state.get("streamrip_runtime_state")

    if not isinstance(cached_streamrip_state, dict):
        _app_debug("Initial streamrip boot load path entered.")
        initial_config_path = _get_streamrip_config_path_hint() or get_streamrip_config_path()
        env_mtime_ns = _get_file_mtime_ns(ENV_FILE_PATH)
        config_mtime_ns = _get_file_mtime_ns(initial_config_path)
        with st.status("Starting Streamrip setup...", expanded=False) as streamrip_boot_status:
            streamrip_boot_status.update(label="Resolving Streamrip runtime state...", state="running")
            boot_status_callback = _make_streamrip_boot_status_callback(streamrip_boot_status)
            cached_snapshot = _read_streamrip_runtime_snapshot(env_mtime_ns, config_mtime_ns)
            if cached_snapshot is not None:
                _app_debug("Restoring streamrip runtime state from snapshot cache.")
                streamrip_boot_status.update(label="Restoring Streamrip runtime state from cache...", state="running")
                (
                    streamrip_config_path,
                    streamrip_config_ready,
                    streamrip_config_init_msg,
                    streamrip_settings,
                    streamrip_settings_error,
                    env_qobuz_app_id,
                    env_qobuz_token,
                ) = cached_snapshot
            else:
                (
                    streamrip_config_path,
                    streamrip_config_ready,
                    streamrip_config_init_msg,
                    streamrip_settings,
                    streamrip_settings_error,
                    env_qobuz_app_id,
                    env_qobuz_token,
                ) = _load_streamrip_runtime_state_cached(
                    env_mtime_ns,
                    initial_config_path,
                    config_mtime_ns,
                    _status_callback=boot_status_callback,
                )
            streamrip_boot_status.update(label="Streamrip setup ready.", state="complete")
        _cache_streamrip_runtime_state(
            streamrip_config_path,
            streamrip_config_ready,
            streamrip_config_init_msg,
            streamrip_settings,
            streamrip_settings_error,
            env_qobuz_app_id,
            env_qobuz_token,
        )
    else:
        if _streamrip_runtime_cache_is_stale(cached_streamrip_state):
            _app_debug("Streamrip runtime cache stale; refreshing runtime state.")
            (
                streamrip_config_path,
                streamrip_config_ready,
                streamrip_config_init_msg,
                streamrip_settings,
                streamrip_settings_error,
                env_qobuz_app_id,
                env_qobuz_token,
            ) = _load_streamrip_runtime_state()
            _cache_streamrip_runtime_state(
                streamrip_config_path,
                streamrip_config_ready,
                streamrip_config_init_msg,
                streamrip_settings,
                streamrip_settings_error,
                env_qobuz_app_id,
                env_qobuz_token,
            )
        else:
            _app_debug("Using cached streamrip runtime state.")
            streamrip_config_path = str(cached_streamrip_state.get("config_path", ""))
            streamrip_config_ready = bool(cached_streamrip_state.get("config_ready", False))
            streamrip_config_init_msg = str(cached_streamrip_state.get("config_init_msg", ""))
            streamrip_settings = dict(cached_streamrip_state.get("settings", {}) or {})
            streamrip_settings_error = str(cached_streamrip_state.get("settings_error", ""))
            env_qobuz_app_id = str(cached_streamrip_state.get("qobuz_app_id", ""))
            env_qobuz_token = str(cached_streamrip_state.get("qobuz_token", ""))

    if streamrip_config_ready and streamrip_settings:
        current_streamrip_token = str(streamrip_settings.get("password_or_token", "")).strip()
        current_streamrip_app_id = str(streamrip_settings.get("app_id", "")).strip()
        current_streamrip_identifier = str(streamrip_settings.get("email_or_userid", "")).strip()
        active_qobuz_app_id = current_streamrip_app_id or str(env_qobuz_app_id or "").strip()

        env_mtime_ns = _get_file_mtime_ns(ENV_FILE_PATH)
        config_mtime_ns = _get_file_mtime_ns(streamrip_config_path)
        env_token_newer_than_streamrip = bool(
            str(env_qobuz_token or "").strip()
            and str(env_qobuz_token or "").strip() != current_streamrip_token
            and env_mtime_ns > config_mtime_ns
        )
        env_sync_marker = (
            f"{env_mtime_ns}:{_token_fingerprint(env_qobuz_token)}:{_token_fingerprint(active_qobuz_app_id)}"
        )
        env_sync_marker_key = "qobuz_env_token_sync_marker"
        already_processed_marker = str(st.session_state.get(env_sync_marker_key, ""))
        should_attempt_env_sync = env_token_newer_than_streamrip and (already_processed_marker != env_sync_marker)

        if should_attempt_env_sync:
            _app_debug("Detected newer .env token than streamrip config; validating and auto-filling from /user/login.")
            st.session_state[env_sync_marker_key] = env_sync_marker
            remember_session_snapshot_value(env_sync_marker_key, env_sync_marker)
            if not active_qobuz_app_id:
                _app_debug("Skipped newer env token sync because no app ID is available.")
            else:
                ok_info, info_data, info_msg = fetch_qobuz_account_info(active_qobuz_app_id, env_qobuz_token)
                if ok_info:
                    resolved_identifier = _pick_streamrip_identifier_from_account(info_data, current_streamrip_identifier)
                    save_ok, save_msg = save_streamrip_settings(
                        streamrip_config_path,
                        use_auth_token=True,
                        email_or_userid=resolved_identifier,
                        password_or_token=env_qobuz_token,
                        app_id=active_qobuz_app_id,
                        quality=int(streamrip_settings.get("quality", 3)),
                        codec_selection=str(streamrip_settings.get("codec_selection", "Original")),
                        downloads_folder=str(streamrip_settings.get("downloads_folder", "")),
                        downloads_db_path=str(streamrip_settings.get("downloads_db_path", "")),
                        failed_downloads_path=str(streamrip_settings.get("failed_downloads_path", "")),
                    )
                    if save_ok:
                        _app_debug("Newer env token sync succeeded; streamrip credentials auto-filled from Qobuz login payload.")
                        st.session_state.qobuz_autofill_notice = (
                            "Detected a newer token in `.env`. Verified it with Qobuz and auto-filled Streamrip "
                            f"credentials (token, App ID, identifier: `{resolved_identifier}`)."
                        )
                        remember_session_snapshot_value("qobuz_autofill_notice", st.session_state.qobuz_autofill_notice)
                        normalized_cache = {
                            "ok": True,
                            "message": str(info_msg or ""),
                            "app_id": str(active_qobuz_app_id),
                            "token_fingerprint": _token_fingerprint(env_qobuz_token),
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "data": dict(info_data or {}),
                            "subscription_expires_at": str(info_data.get("subscription_expires_at", "")),
                        }
                        st.session_state["qobuz_account_info_cache"] = normalized_cache
                        remember_session_snapshot_value("qobuz_account_info_cache", normalized_cache)
                        streamrip_settings, streamrip_settings_error = load_streamrip_settings(streamrip_config_path)
                        _cache_streamrip_runtime_state(
                            streamrip_config_path,
                            streamrip_config_ready,
                            streamrip_config_init_msg,
                            streamrip_settings,
                            streamrip_settings_error,
                            env_qobuz_app_id,
                            env_qobuz_token,
                        )
                    else:
                        _app_debug(f"Newer env token sync save failed: {save_msg}")
                else:
                    _app_debug(f"Newer env token validation failed; streamrip config not changed. reason={info_msg}")

    if main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip"}:
        if streamrip_config_init_msg:
            _app_debug(f"Sidebar info shown: {streamrip_config_init_msg}")
            st.sidebar.info(streamrip_config_init_msg)
        if streamrip_settings_error:
            _app_debug(f"Sidebar warning shown: {streamrip_settings_error}")
            st.sidebar.warning(streamrip_settings_error)

    default_rip_quality = int(streamrip_settings.get("quality", 3)) if streamrip_settings else 3
    if default_rip_quality not in QUALITY_OPTIONS:
        default_rip_quality = 3

    default_codec = str(streamrip_settings.get("codec_selection", "Original")) if streamrip_settings else "Original"
    if default_codec not in CODEC_OPTIONS:
        default_codec = "Original"

    default_downloads_folder = str(streamrip_settings.get("downloads_folder", "") or get_default_downloads_folder()).strip()
    init_streamrip_download_state(default_downloads_folder)
    init_streamrip_form_state(
        streamrip_settings=streamrip_settings,
        default_rip_quality=default_rip_quality,
        default_codec=default_codec,
        streamrip_config_path=streamrip_config_path,
    )

    if "active_rip_quality" not in st.session_state or st.session_state.active_rip_quality not in QUALITY_OPTIONS:
        st.session_state.active_rip_quality = default_rip_quality
    if "active_rip_codec" not in st.session_state or st.session_state.active_rip_codec not in CODEC_OPTIONS:
        st.session_state.active_rip_codec = default_codec
    if "wip_matcher" not in st.session_state:
        st.session_state.wip_matcher = False
    if "wip_direct_rip" not in st.session_state:
        st.session_state.wip_direct_rip = False
    if "wip_smoked_salmon" not in st.session_state:
        st.session_state.wip_smoked_salmon = False
    rip_quality = int(st.session_state.active_rip_quality)
    rip_codec = str(st.session_state.active_rip_codec)

    matcher_wip = bool(st.session_state.get("wip_matcher", False))
    direct_rip_wip = bool(st.session_state.get("wip_direct_rip", False))
    smoked_salmon_wip = bool(st.session_state.get("wip_smoked_salmon", False))
    if main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip", "Smoked Salmon Upload", "Smoked Salmon Settings"}:
        with st.sidebar.expander("🚧 WIP Toggles", expanded=False):
            _app_debug("Sidebar: rendering WIP Toggles section.")
            st.caption("Enable WIP lock for the active tab.")
            if main_tab == "Bandcamp Matcher":
                matcher_wip = st.toggle("Bandcamp Matcher WIP", value=matcher_wip, key="wip_matcher", help="Lock controls in this tab while work is in progress.")
                _app_debug(f"WIP toggle state (matcher): {matcher_wip}")
            elif main_tab == "Direct Qobuz Rip":
                direct_rip_wip = st.toggle("Direct Qobuz Rip WIP", value=direct_rip_wip, key="wip_direct_rip", help="Lock controls in this tab while work is in progress.")
                _app_debug(f"WIP toggle state (direct rip): {direct_rip_wip}")
            else:
                smoked_salmon_wip = st.toggle("Smoked Salmon Upload WIP", value=smoked_salmon_wip, key="wip_smoked_salmon", help="Lock controls in this tab while work is in progress.")
                _app_debug(f"WIP toggle state (smoked salmon): {smoked_salmon_wip}")

    has_streamrip_identifier = bool(str(streamrip_settings.get("email_or_userid", "")).strip())
    has_streamrip_token = bool(str(streamrip_settings.get("password_or_token", "")).strip())
    has_streamrip_downloads_folder = bool(str(streamrip_settings.get("downloads_folder", "")).strip())
    has_streamrip_downloads_db_path = bool(str(streamrip_settings.get("downloads_db_path", "")).strip())
    has_streamrip_failed_downloads_path = bool(str(streamrip_settings.get("failed_downloads_path", "")).strip())
    streamrip_installed = is_streamrip_installed()
    streamrip_missing_required_fields = []
    if not has_streamrip_identifier:
        streamrip_missing_required_fields.append("email_or_userid")
    if not has_streamrip_token:
        streamrip_missing_required_fields.append("password_or_token")
    if not has_streamrip_downloads_folder:
        streamrip_missing_required_fields.append("downloads_folder")
    if not has_streamrip_downloads_db_path:
        streamrip_missing_required_fields.append("downloads_db_path")
    if not has_streamrip_failed_downloads_path:
        streamrip_missing_required_fields.append("failed_downloads_path")
    streamrip_needs_setup = (
        not streamrip_config_ready
        or not streamrip_settings
        or not (
            has_streamrip_identifier
            and has_streamrip_token
            and has_streamrip_downloads_folder
            and has_streamrip_downloads_db_path
            and has_streamrip_failed_downloads_path
        )
    )
    _app_debug(f"Computed streamrip_needs_setup={streamrip_needs_setup}.")
    streamrip_rip_disabled_reason = ""
    if streamrip_needs_setup:
        streamrip_rip_disabled_reason = _build_streamrip_rip_disabled_reason(
            installed=streamrip_installed,
            config_ready=streamrip_config_ready,
            config_init_msg=streamrip_config_init_msg,
            settings_error=streamrip_settings_error,
            missing_required_fields=streamrip_missing_required_fields,
        )

    autofill_notice = str(st.session_state.pop("qobuz_autofill_notice", "")).strip()
    if autofill_notice:
        st.success(autofill_notice)

    if "streamrip_setup_matcher_expand_once" not in st.session_state:
        st.session_state.streamrip_setup_matcher_expand_once = False
    if "streamrip_setup_matcher_scroll_once" not in st.session_state:
        st.session_state.streamrip_setup_matcher_scroll_once = False
    if "streamrip_setup_attention_message" not in st.session_state:
        st.session_state.streamrip_setup_attention_message = ""

    if main_tab == "Qobuz Settings":
        streamrip_settings, streamrip_settings_error = render_qobuz_settings_tab(
            streamrip_settings=streamrip_settings,
            streamrip_settings_error=streamrip_settings_error,
            streamrip_config_path=streamrip_config_path,
            streamrip_config_ready=streamrip_config_ready,
            streamrip_config_init_msg=streamrip_config_init_msg,
            default_rip_quality=default_rip_quality,
            default_codec=default_codec,
            default_downloads_folder=default_downloads_folder,
            env_qobuz_app_id=env_qobuz_app_id,
            env_qobuz_token=env_qobuz_token,
            app_debug=_app_debug,
            open_env_for_qobuz=_open_env_for_qobuz,
            cache_streamrip_runtime_state=_cache_streamrip_runtime_state,
        )

    if main_tab == "Streamrip Settings":
        render_streamrip_settings_tab(
            streamrip_config_init_msg=streamrip_config_init_msg,
            streamrip_settings_error=streamrip_settings_error,
            streamrip_needs_setup=streamrip_needs_setup,
            streamrip_config_path=streamrip_config_path,
            streamrip_config_ready=streamrip_config_ready,
            streamrip_settings=streamrip_settings,
            default_rip_quality=default_rip_quality,
            default_codec=default_codec,
            env_qobuz_app_id=env_qobuz_app_id,
            env_qobuz_token=env_qobuz_token,
            streamrip_missing_required_fields=streamrip_missing_required_fields,
            on_rip_quality_change=_on_rip_quality_change,
            app_debug=_app_debug,
        )

    if main_tab == "Bandcamp Matcher":
        if matcher_wip:
            render_wip_notice()
        matcher_requires_env_token = (not dry_run) and (not bool(str(env_qobuz_token).strip()))
        if matcher_requires_env_token:
            st.warning("Actions in this tab are disabled until `QOBUZ_USER_AUTH_TOKEN` is set in `.env` (or enable Dry Run).")
            if st.button("Open Qobuz Settings Tab", key="matcher_open_qobuz_settings"):
                st.session_state.main_tab_selection_pending = "Qobuz Settings"
                st.rerun()

        uploaded_file = st.file_uploader(
            "Upload .txt or .log file with Bandcamp URLs",
            type=["txt", "log"],
            disabled=matcher_wip,
        )

        validation_errors = validate_filters(
            min_tracks,
            max_tracks,
            min_duration,
            max_duration,
            start_date,
            end_date,
        )
        if validation_errors:
            for err in validation_errors:
                st.session_state.auto_scroll_alerts_once = True
                st.error(err)

        filter_config = {
            "tag": tag_input,
            "exclude_tag": exclude_tag_input,
            "location": location_input,
            "min_tracks": int(min_tracks) if min_tracks else None,
            "max_tracks": int(max_tracks) if max_tracks else None,
            "min_duration": int(min_duration) if min_duration else None,
            "max_duration": int(max_duration) if max_duration else None,
            "free_mode": free_mode,
            "only_24bit": only_24bit,
            "check_red": check_red,
            "check_ops": check_ops,
        }

        col1, col2, col3 = st.columns([1.2, 1.6, 4])
        with col1:
            process_btn = st.button(
                "Process",
                type="primary",
                disabled=matcher_wip or bool(validation_errors) or matcher_requires_env_token,
                help=(
                    "Disabled until QOBUZ_USER_AUTH_TOKEN is set in `.env` (unless Dry Run is enabled)."
                    if matcher_requires_env_token
                    else "Run Bandcamp filtering and Qobuz matching."
                ),
            )
        with col2:
            auto_rip_help_text = (
                streamrip_rip_disabled_reason
                if streamrip_needs_setup
                else "Automatically run streamrip after exporting this run's Qobuz results."
            )
            auto_rip_after_export = st.toggle(
                "Auto rip after export",
                value=False,
                key="matcher_auto_rip_after_export",
                help=auto_rip_help_text,
                disabled=matcher_wip or streamrip_needs_setup,
            )
        with col3:
            stop_btn = st.button(
                "Stop / Cancel",
                help="Stops after the current in-flight batch and shows partial results.",
                disabled=matcher_wip or not st.session_state.processing,
            )

        if stop_btn and st.session_state.processing:
            st.session_state.cancel_requested = True
            st.info("Stop requested. Processing will end after the current batch.")

        handle_process_submission(
            process_btn=process_btn,
            uploaded_file=uploaded_file,
            filter_config=filter_config,
            start_date=start_date,
            end_date=end_date,
            dry_run=dry_run,
            rate_limit_config={
                "concurrency": int(ui_concurrency),
                "request_delay": float(ui_request_delay),
                "qobuz_retries": int(ui_qobuz_retries),
                "qobuz_retry_delay": float(ui_qobuz_retry_delay),
                "bc_retries": int(ui_bc_retries),
                "bc_retry_delay": float(ui_bc_retry_delay),
            },
        )

        run_processing_tick()
        render_status_log(dry_run=dry_run)
        render_results_and_exports(
            dry_run=dry_run,
            rip_quality=rip_quality,
            rip_codec=rip_codec,
            auto_rip_after_export=auto_rip_after_export,
            streamrip_needs_setup=streamrip_needs_setup,
            streamrip_missing_required_fields=streamrip_missing_required_fields,
            streamrip_rip_disabled_reason=streamrip_rip_disabled_reason,
        )
    elif main_tab == "Direct Qobuz Rip":
        if direct_rip_wip:
            render_wip_notice()
        render_direct_qobuz_rip_tab(
            rip_quality=rip_quality,
            rip_codec=rip_codec,
            streamrip_needs_setup=streamrip_needs_setup,
            streamrip_missing_required_fields=streamrip_missing_required_fields,
            locked=direct_rip_wip,
        )
    elif main_tab == "Smoked Salmon Upload":
        render_smoked_salmon_tab(
            default_downloads_folder=default_downloads_folder,
            locked=smoked_salmon_wip,
            show_settings=False,
            show_upload=True,
        )
    elif main_tab == "Smoked Salmon Settings":
        render_smoked_salmon_tab(
            default_downloads_folder=default_downloads_folder,
            locked=smoked_salmon_wip,
            show_settings=True,
            show_upload=False,
        )

    _render_alert_scroll_if_requested()


main()
