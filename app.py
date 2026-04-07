import os

import streamlit as st
from dotenv import load_dotenv
from app_modules.debug_logging import emit_debug

from app_modules.filtering import validate_filters
from app_modules.streamrip import (
    CODEC_OPTIONS,
    QUALITY_OPTIONS,
    ensure_streamrip_config_file,
    format_quality_option,
    get_default_downloads_folder,
    get_env_qobuz_values,
    get_streamrip_config_path,
    is_streamrip_installed,
    load_streamrip_settings,
    save_streamrip_settings,
)
from app_modules.system_utils import open_in_default_app
from app_modules.ui_processing import (
    handle_process_submission,
    render_results_and_exports,
    render_status_log,
    run_processing_tick,
)
from app_modules.ui_modal import (
    init_qobuz_help_state,
    open_qobuz_help_modal,
    render_modal_base_styles,
    render_qobuz_help_modals,
)
from app_modules.ui_smoked_salmon import render_smoked_salmon_tab
from app_modules.ui_state import init_session_state, remember_session_snapshot_value
from app_modules.ui_streamrip_setup import (
    init_streamrip_download_state,
    init_streamrip_form_state,
    render_streamrip_setup,
)
from app_modules.ui_tools import render_direct_qobuz_rip_tab

load_dotenv()

st.set_page_config(page_title="Bandcamp to Qobuz Matcher", layout="wide")
st.title("🎵 Bandcamp to Qobuz Matcher")
st.markdown("Filter your Bandcamp URLs and find exact high-resolution matches on Qobuz.")
render_modal_base_styles()


def _app_debug(message: str) -> None:
    emit_debug("app", message)


def render_wip_notice() -> None:
    st.markdown(
        f"""
        <div style="
            margin: 0.4rem 0 1rem 0;
            padding: 0.9rem 1rem;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.18);
            background: linear-gradient(135deg, rgba(0,0,0,0.72), rgba(20,20,20,0.78));
            color: #f2f2f2;
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


def _get_file_mtime_ns(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


def _get_env_mtime_ns(env_path: str = ".env") -> int:
    return _get_file_mtime_ns(env_path)


def _sync_env_file_changes() -> None:
    current_mtime_ns = _get_env_mtime_ns(".env")
    previous_mtime_ns = st.session_state.get("_env_file_mtime_ns")
    if previous_mtime_ns is None:
        st.session_state._env_file_mtime_ns = current_mtime_ns
        return
    if current_mtime_ns != previous_mtime_ns:
        st.session_state._env_file_mtime_ns = current_mtime_ns
        load_dotenv(override=True)
        _app_debug("Detected .env file change; reloaded environment values.")


def _mount_env_watchdog() -> None:
    # Keep env sync deterministic and avoid background fragment rerun churn.
    _sync_env_file_changes()


def _render_alert_scroll_if_requested() -> None:
    if not st.session_state.get("auto_scroll_alerts_once", False):
        return
    st.iframe(
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
    st.session_state.auto_scroll_alerts_once = False


init_session_state()
init_qobuz_help_state()
_mount_env_watchdog()

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

main_tab = st.radio(
    "Main Tab",
    options=["Bandcamp Matcher", "Direct Qobuz Rip", "Smoked Salmon Upload"],
    key="main_tab_selection",
    horizontal=True,
    label_visibility="collapsed",
)
_app_debug(f"Main tab selected: `{main_tab}`.")

st.sidebar.header("Configuration")
_app_debug("Sidebar: Configuration header rendered.")

tag_input = ""
exclude_tag_input = ""
location_input = ""
min_tracks = None
max_tracks = None
min_duration = None
max_duration = None
start_date = None
end_date = None
free_mode = "All"
dry_run = False

if main_tab == "Bandcamp Matcher":
    _app_debug("Sidebar: rendering matcher filter/date/run settings.")
    with st.sidebar.expander("🎯 Matcher Filter Rules", expanded=False):
        tag_input = st.text_input("Include Genre / Tag", value="", help="Filter by tag or genre. Separate multiple with commas (e.g. 'rock, jazz').")
        exclude_tag_input = st.text_input("Exclude Genre / Tag", value="", help="Exclude tags or genres. Separate multiple with commas.")
        location_input = st.text_input("Location", value="", help="Filter by location text in metadata.")
        min_tracks = st.number_input("Min Tracks", min_value=1, value=None, step=1, help="Leave empty for no minimum.")
        max_tracks = st.number_input("Max Tracks", min_value=1, value=None, step=1, help="Leave empty for no maximum.")
        min_duration = st.number_input("Min Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no minimum.")
        max_duration = st.number_input("Max Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no maximum.")

    with st.sidebar.expander("📅 Matcher Release Date Filter", expanded=False):
        start_date = st.date_input("Start Date", value=None, help="Filter for releases on or after this date.")
        end_date = st.date_input("End Date", value=None, help="Filter for releases on or before this date.")

    with st.sidebar.expander("⚙️ Matcher Run Settings", expanded=True):
        free_mode = st.selectbox("Pricing", options=["All", "Free", "Paid"], index=0)
        dry_run = st.checkbox("Dry Run", value=False, help="Only apply Bandcamp filter, skip Qobuz search.")

if main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip"}:
    _app_debug("Sidebar: rendering Qobuz Token section.")
    with st.sidebar.expander("🔐 Qobuz Token", expanded=(main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip"})):
        open_env_btn = st.button("📝 Open .env for Qobuz Token", use_container_width=True)
        qobuz_help_btn = st.button("Get Qobuz Token", use_container_width=True)

        if open_env_btn:
            _app_debug("Sidebar action: Open .env button clicked.")
            env_path = ".env"
            if not os.path.exists(env_path):
                template = """# Important: So that Python recognizes local directories (e.g., logic) as modules
PYTHONPATH=.
# Optional: Set your own Qobuz App ID (if omitted, the app auto-fetches it from Qobuz Web Player)
# QOBUZ_APP_ID=
# Required (depending on region/account type): Set your user Auth Token for Qobuz
QOBUZ_USER_AUTH_TOKEN="""
                try:
                    with open(env_path, "w", encoding="utf-8") as f:
                        f.write(template)
                except Exception as e:
                    _app_debug(f"Failed creating .env template file: {e}")
                    st.session_state.auto_scroll_alerts_once = True
                    st.error(f"Error creating the .env file: {e}")

            try:
                open_in_default_app(env_path)
                _app_debug("Opened .env in default app.")
            except Exception as e:
                _app_debug(f"Failed opening .env in default app: {e}")
                st.session_state.auto_scroll_alerts_once = True
                st.error(f"Could not open .env: {e}")

        if qobuz_help_btn:
            _app_debug("Sidebar action: Get Qobuz Token button clicked.")
            open_qobuz_help_modal()

render_qobuz_help_modals()

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
    qobuz_app_id, qobuz_token = get_env_qobuz_values(status_callback=status_callback)
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


@st.cache_data(show_spinner=False)
def _load_streamrip_runtime_state_cached(
    env_mtime_ns: int,
    config_path_hint: str,
    config_mtime_ns: int,
) -> tuple[str, bool, str, dict, str, str, str]:
    # Cache key is fully represented by function args; values are intentionally unused.
    _ = (env_mtime_ns, config_path_hint, config_mtime_ns)
    _app_debug("Loading streamrip runtime state via process cache.")
    return _load_streamrip_runtime_state()


@st.cache_resource
def _streamrip_runtime_snapshot_store() -> dict:
    return {"key": None, "state": None, "config_path_hint": ""}


def _snapshot_streamrip_runtime_state(
    env_mtime_ns: int,
    config_mtime_ns: int,
    state: tuple[str, bool, str, dict, str, str, str],
) -> None:
    store = _streamrip_runtime_snapshot_store()
    store["key"] = (int(env_mtime_ns), int(config_mtime_ns))
    store["state"] = state
    store["config_path_hint"] = str(state[0] or "")


def _read_streamrip_runtime_snapshot(
    env_mtime_ns: int,
    config_mtime_ns: int,
) -> tuple[str, bool, str, dict, str, str, str] | None:
    store = _streamrip_runtime_snapshot_store()
    if store.get("key") != (int(env_mtime_ns), int(config_mtime_ns)):
        return None
    state = store.get("state")
    if isinstance(state, tuple) and len(state) == 7:
        return state
    return None


def _get_streamrip_config_path_hint() -> str:
    store = _streamrip_runtime_snapshot_store()
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
        "env_mtime_ns": _get_env_mtime_ns(".env"),
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
    current_env_mtime = _get_env_mtime_ns(".env")
    current_config_mtime = _get_file_mtime_ns(config_path)
    cached_env_mtime = _safe_int(cache.get("env_mtime_ns", -2), -2)
    cached_config_mtime = _safe_int(cache.get("config_mtime_ns", -2), -2)
    return (cached_env_mtime != current_env_mtime) or (cached_config_mtime != current_config_mtime)


cached_streamrip_state = st.session_state.get("streamrip_runtime_state")

if not isinstance(cached_streamrip_state, dict):
    _app_debug("Initial streamrip boot load path entered.")
    initial_config_path = _get_streamrip_config_path_hint() or get_streamrip_config_path()
    env_mtime_ns = _get_env_mtime_ns(".env")
    config_mtime_ns = _get_file_mtime_ns(initial_config_path)
    with st.status("Starting Streamrip setup...", expanded=False) as streamrip_boot_status:
        streamrip_boot_status.update(label="Resolving Streamrip runtime state...", state="running")
        cached_snapshot = _read_streamrip_runtime_snapshot(env_mtime_ns, config_mtime_ns)
        if cached_snapshot is not None:
            _app_debug("Restoring streamrip runtime state from snapshot cache.")
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

if streamrip_config_ready and streamrip_settings and env_qobuz_token:
    needs_token = not str(streamrip_settings.get("password_or_token", "")).strip()
    needs_app_id = bool(env_qobuz_app_id) and not str(streamrip_settings.get("app_id", "")).strip()
    if needs_token or needs_app_id:
        _app_debug(
            "Applying env token/app-id into streamrip config due to missing saved values "
            f"(needs_token={needs_token}, needs_app_id={needs_app_id})."
        )
        _ok, _msg = save_streamrip_settings(
            streamrip_config_path,
            use_auth_token=True,
            email_or_userid=str(streamrip_settings.get("email_or_userid", "")),
            password_or_token=env_qobuz_token,
            app_id=env_qobuz_app_id or str(streamrip_settings.get("app_id", "")),
            quality=int(streamrip_settings.get("quality", 3)),
            codec_selection=str(streamrip_settings.get("codec_selection", "Original")),
            downloads_folder=str(streamrip_settings.get("downloads_folder", "")),
            downloads_db_path=str(streamrip_settings.get("downloads_db_path", "")),
            failed_downloads_path=str(streamrip_settings.get("failed_downloads_path", "")),
        )
        if _ok:
            _app_debug("Env token/app-id sync to streamrip config succeeded.")
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
            _app_debug(f"Env token/app-id sync to streamrip config failed: {_msg}")

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

rip_quality = default_rip_quality
rip_codec = default_codec
if main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip"}:
    _app_debug("Sidebar: rendering Streamrip Settings section.")
    with st.sidebar.expander("⚙️ Streamrip Settings", expanded=(main_tab == "Direct Qobuz Rip")):
        rip_quality = st.selectbox(
            "Rip Quality",
            options=QUALITY_OPTIONS,
            index=QUALITY_OPTIONS.index(default_rip_quality),
            format_func=format_quality_option,
            help="Applied to rip commands (equivalent to --quality).",
        )
        rip_codec = st.selectbox(
            "Rip Codec",
            options=CODEC_OPTIONS,
            index=CODEC_OPTIONS.index(default_codec),
            help="Applied to rip commands (equivalent to --codec). Use Original for no conversion flag.",
        )
        st.caption("Qobuz and Tidal ripping requires a premium subscription.")
    _app_debug(f"Sidebar selections: rip_quality={rip_quality}, rip_codec={rip_codec}.")

matcher_wip = bool(st.session_state.get("wip_matcher", False))
direct_rip_wip = bool(st.session_state.get("wip_direct_rip", False))
smoked_salmon_wip = bool(st.session_state.get("wip_smoked_salmon", True))
with st.sidebar.expander("🚧 WIP Toggles", expanded=False):
    _app_debug("Sidebar: rendering WIP Toggles section.")
    st.caption("Enable WIP lock for the active tab.")
    if main_tab == "Bandcamp Matcher":
        matcher_wip = st.toggle("Bandcamp Matcher WIP", value=matcher_wip, key="wip_matcher")
        _app_debug(f"WIP toggle state (matcher): {matcher_wip}")
    elif main_tab == "Direct Qobuz Rip":
        direct_rip_wip = st.toggle("Direct Qobuz Rip WIP", value=direct_rip_wip, key="wip_direct_rip")
        _app_debug(f"WIP toggle state (direct rip): {direct_rip_wip}")
    else:
        smoked_salmon_wip = st.toggle("Smoked Salmon Upload WIP", value=smoked_salmon_wip, key="wip_smoked_salmon")
        _app_debug(f"WIP toggle state (smoked salmon): {smoked_salmon_wip}")

has_streamrip_identifier = bool(str(streamrip_settings.get("email_or_userid", "")).strip())
has_streamrip_token = bool(str(streamrip_settings.get("password_or_token", "")).strip())
has_streamrip_downloads_folder = bool(str(streamrip_settings.get("downloads_folder", "")).strip())
has_streamrip_downloads_db_path = bool(str(streamrip_settings.get("downloads_db_path", "")).strip())
has_streamrip_failed_downloads_path = bool(str(streamrip_settings.get("failed_downloads_path", "")).strip())
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

if "streamrip_setup_matcher_expand_once" not in st.session_state:
    st.session_state.streamrip_setup_matcher_expand_once = False
if "streamrip_setup_matcher_scroll_once" not in st.session_state:
    st.session_state.streamrip_setup_matcher_scroll_once = False
if "streamrip_setup_attention_message" not in st.session_state:
    st.session_state.streamrip_setup_attention_message = ""

if main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip"}:
    _app_debug("Rendering shared Streamrip setup section from sidebar flow.")
    render_streamrip_setup(
        streamrip_needs_setup=streamrip_needs_setup,
        streamrip_config_path=streamrip_config_path,
        streamrip_config_ready=streamrip_config_ready,
        streamrip_settings=streamrip_settings,
        default_rip_quality=default_rip_quality,
        default_codec=default_codec,
        env_qobuz_app_id=env_qobuz_app_id,
        env_qobuz_token=env_qobuz_token,
        expanded_override=(streamrip_needs_setup or bool(st.session_state.streamrip_setup_matcher_expand_once)),
        key_prefix="shared_streamrip_setup",
        include_browser=True,
    )
    if st.session_state.streamrip_setup_attention_message:
        _app_debug(f"Streamrip setup attention warning shown: {st.session_state.streamrip_setup_attention_message}")
        st.warning(st.session_state.streamrip_setup_attention_message)
        st.session_state.streamrip_setup_attention_message = ""
    if st.session_state.streamrip_setup_matcher_scroll_once:
        st.iframe(
            """
            <script>
                const doc = window.parent.document;
                const root = doc.querySelector("section.main");
                if (root) {
                    root.scrollTo({ top: 0, behavior: "smooth" });
                } else {
                    window.parent.scrollTo({ top: 0, behavior: "smooth" });
                }
            </script>
            """,
            height=1,
        )
        st.session_state.streamrip_setup_matcher_scroll_once = False
    st.session_state.streamrip_setup_matcher_expand_once = False

if main_tab == "Bandcamp Matcher":
    if matcher_wip:
        render_wip_notice()

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
    }

    col1, col2, col3 = st.columns([1.2, 1.6, 4])
    with col1:
        process_btn = st.button("Process", type="primary", disabled=matcher_wip or bool(validation_errors))
    with col2:
        auto_rip_after_export = st.toggle(
            "Auto rip after export",
            value=False,
            help="Automatically run streamrip after exporting this run's Qobuz results.",
            disabled=matcher_wip,
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
    )

    run_processing_tick()
    render_status_log(dry_run=dry_run)
    render_results_and_exports(
        dry_run=dry_run,
        rip_quality=rip_quality,
        rip_codec=rip_codec,
        auto_rip_after_export=auto_rip_after_export,
        streamrip_needs_setup=streamrip_needs_setup,
    )
elif main_tab == "Direct Qobuz Rip":
    if direct_rip_wip:
        render_wip_notice()
    render_direct_qobuz_rip_tab(
        rip_quality=rip_quality,
        rip_codec=rip_codec,
        streamrip_needs_setup=streamrip_needs_setup,
        locked=direct_rip_wip,
    )
else:
    render_smoked_salmon_tab(default_downloads_folder=default_downloads_folder, locked=smoked_salmon_wip)

_render_alert_scroll_if_requested()
