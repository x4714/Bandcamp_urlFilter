import os
import sys
from datetime import datetime, timezone

import streamlit as st

from app_modules.debug_logging import emit_debug
from app_modules.filesystem import list_directory_entries
from app_modules.streamrip import (
    CODEC_OPTIONS,
    QUALITY_OPTIONS,
    fetch_qobuz_user_identifier,
    format_quality_option,
    get_streamrip_config_path,
    get_streamrip_database_defaults,
    is_streamrip_installed,
    read_streamrip_config_text,
    save_streamrip_settings,
)


def _setup_debug(message: str) -> None:
    emit_debug("streamrip setup", message)


def init_streamrip_form_state(
    streamrip_settings: dict,
    default_rip_quality: int,
    default_codec: str,
    streamrip_config_path: str | None = None,
) -> None:
    _setup_debug("init_streamrip_form_state() called.")
    resolved_config_path = streamrip_config_path or get_streamrip_config_path()
    use_auth = bool(streamrip_settings.get("use_auth_token", True))
    email_or_userid = str(streamrip_settings.get("email_or_userid", ""))
    password_or_token = str(streamrip_settings.get("password_or_token", ""))
    app_id = str(streamrip_settings.get("app_id", ""))
    quality = int(streamrip_settings.get("quality", default_rip_quality))
    codec = str(streamrip_settings.get("codec_selection", default_codec))
    downloads_folder = str(streamrip_settings.get("downloads_folder", ""))
    default_db_path, default_failed_path = get_streamrip_database_defaults(resolved_config_path)
    downloads_db_path = str(streamrip_settings.get("downloads_db_path", default_db_path))
    failed_downloads_path = str(streamrip_settings.get("failed_downloads_path", default_failed_path))

    if quality not in QUALITY_OPTIONS:
        _setup_debug(
            f"Invalid configured quality `{quality}`; falling back to default `{default_rip_quality}`."
        )
        quality = default_rip_quality
    if codec not in CODEC_OPTIONS:
        _setup_debug(
            f"Invalid configured codec `{codec}`; falling back to default `{default_codec}`."
        )
        codec = default_codec

    signature = (
        use_auth,
        email_or_userid,
        password_or_token,
        app_id,
        quality,
        codec,
        downloads_folder,
        downloads_db_path,
        failed_downloads_path,
    )
    if st.session_state.get("streamrip_form_settings_signature") == signature:
        _setup_debug("Form state signature unchanged; skipping re-init.")
        return

    st.session_state.streamrip_form_use_auth_token = use_auth
    st.session_state.streamrip_form_email_or_userid = email_or_userid
    st.session_state.streamrip_form_password_or_token = password_or_token
    st.session_state.streamrip_form_app_id = app_id
    st.session_state.streamrip_form_quality = quality
    st.session_state.streamrip_form_codec = codec
    st.session_state.streamrip_form_downloads_folder = downloads_folder
    st.session_state.streamrip_form_downloads_db_path = downloads_db_path
    st.session_state.streamrip_form_failed_downloads_path = failed_downloads_path
    st.session_state.streamrip_form_settings_signature = signature
    _setup_debug("Streamrip form state initialized/refreshed from settings.")


def init_streamrip_download_state(default_downloads_folder: str) -> None:
    _setup_debug("init_streamrip_download_state() called.")
    if "streamrip_downloads_folder_persist" not in st.session_state:
        st.session_state.streamrip_downloads_folder_persist = default_downloads_folder
    if "streamrip_downloads_folder_draft" not in st.session_state:
        st.session_state.streamrip_downloads_folder_draft = str(st.session_state.streamrip_downloads_folder_persist)
    else:
        st.session_state.streamrip_downloads_folder_persist = str(st.session_state.streamrip_downloads_folder_draft)
    if "streamrip_browser_path" not in st.session_state:
        start_path = st.session_state.streamrip_downloads_folder_draft or os.path.expanduser("~")
        st.session_state.streamrip_browser_path = start_path if os.path.isdir(start_path) else os.path.expanduser("~")
    _setup_debug(
        f"Download state ready. draft=`{st.session_state.streamrip_downloads_folder_draft}`, "
        f"browser_path=`{st.session_state.streamrip_browser_path}`"
    )


def render_streamrip_setup(
    streamrip_needs_setup: bool,
    streamrip_config_path: str,
    streamrip_config_ready: bool,
    streamrip_settings: dict,
    default_rip_quality: int,
    default_codec: str,
    env_qobuz_app_id: str,
    env_qobuz_token: str,
    expanded_override: bool | None = None,
    key_prefix: str = "streamrip_setup",
    include_browser: bool = False,
) -> None:
    _setup_debug(
        f"render_streamrip_setup() called. needs_setup={streamrip_needs_setup}, "
        f"config_ready={streamrip_config_ready}, include_browser={include_browser}"
    )

    def _show_error(message: str) -> None:
        _setup_debug(f"UI error shown: {message}")
        st.session_state.streamrip_setup_matcher_scroll_once = True
        st.session_state.auto_scroll_alerts_once = True
        st.error(message)

    def _k(name: str) -> str:
        return f"{key_prefix}_{name}"

    def _prime_widget(widget_name: str, shared_key: str) -> None:
        widget_key = _k(widget_name)
        shared_value = st.session_state.get(shared_key)
        current_signature = st.session_state.get("streamrip_form_settings_signature")
        sync_marker_key = f"{widget_key}__synced_signature"
        needs_sync = st.session_state.get(sync_marker_key) != current_signature
        if not needs_sync:
            if widget_key not in st.session_state:
                needs_sync = True
            elif isinstance(shared_value, str):
                widget_value = st.session_state.get(widget_key, "")
                # Re-prime text inputs when saved/shared value exists but widget state is blank.
                if shared_value.strip() and not str(widget_value).strip():
                    needs_sync = True
        if needs_sync:
            st.session_state[widget_key] = shared_value
            st.session_state[sync_marker_key] = current_signature
            _setup_debug(f"Widget primed `{widget_key}` from `{shared_key}`.")

    _prime_widget("use_auth_token", "streamrip_form_use_auth_token")
    _prime_widget("email_or_userid", "streamrip_form_email_or_userid")
    _prime_widget("password_or_token", "streamrip_form_password_or_token")
    _prime_widget("app_id", "streamrip_form_app_id")
    _prime_widget("downloads_folder_draft", "streamrip_form_downloads_folder")
    _prime_widget("downloads_db_path_draft", "streamrip_form_downloads_db_path")
    _prime_widget("failed_downloads_path_draft", "streamrip_form_failed_downloads_path")
    _prime_widget("cfg_quality", "streamrip_form_quality")
    _prime_widget("cfg_codec", "streamrip_form_codec")

    expanded_value = streamrip_needs_setup if expanded_override is None else bool(expanded_override)
    with st.expander("🎧 Streamrip Setup", expanded=expanded_value):
        st.caption(f"Config path: `{streamrip_config_path}`")
        installed = is_streamrip_installed()
        status_color = "green" if installed else "red"
        status_text = "Installed" if installed else "Not Found"
        st.markdown(f"Status: <span style='color:{status_color}; font-weight:bold;'>{status_text}</span>", unsafe_allow_html=True)
        
        if not streamrip_config_ready:
            _show_error("Streamrip config is not available yet. Install streamrip and restart the app.")
        else:
            col_setup1, col_setup2, col_setup3 = st.columns([1, 1, 1])
            with col_setup1:
                if st.button(
                    "Auto-Fill Token/App ID from .env",
                    help="Copies QOBUZ_USER_AUTH_TOKEN and optional QOBUZ_APP_ID from .env into Streamrip config fields.",
                    key=_k("autofill_btn"),
                ):
                    _setup_debug("Auto-Fill Token/App ID button clicked.")
                    current_use_auth = bool(st.session_state.get("streamrip_form_use_auth_token", True))
                    current_email = str(st.session_state.get("streamrip_form_email_or_userid", ""))
                    current_token = str(st.session_state.get("streamrip_form_password_or_token", ""))
                    current_app_id = str(st.session_state.get("streamrip_form_app_id", ""))
                    current_quality = int(st.session_state.get("streamrip_form_quality", default_rip_quality))
                    current_codec = str(st.session_state.get("streamrip_form_codec", default_codec))
                    current_downloads = str(
                        st.session_state.get(
                            "streamrip_form_downloads_folder",
                            st.session_state.streamrip_downloads_folder_draft,
                        )
                    )
                    current_downloads_db_path = str(
                        st.session_state.get("streamrip_form_downloads_db_path", "")
                    )
                    current_failed_downloads_path = str(
                        st.session_state.get("streamrip_form_failed_downloads_path", "")
                    )

                    updated_token = env_qobuz_token or current_token
                    updated_app_id = env_qobuz_app_id or current_app_id
                    ok, msg = save_streamrip_settings(
                        streamrip_config_path,
                        use_auth_token=(True if env_qobuz_token else current_use_auth),
                        email_or_userid=current_email,
                        password_or_token=updated_token,
                        app_id=updated_app_id,
                        quality=current_quality,
                        codec_selection=current_codec,
                        downloads_folder=current_downloads,
                        downloads_db_path=current_downloads_db_path,
                        failed_downloads_path=current_failed_downloads_path,
                    )
                    if ok:
                        _setup_debug("Auto-fill save succeeded; rerunning app.")
                        st.success(msg)
                        st.rerun()
                    else:
                        _setup_debug("Auto-fill save failed.")
                        _show_error(msg)
            with col_setup2:
                if st.button(
                    "Fetch User ID / Email",
                    help="Calls Qobuz login API with your token/app ID and writes the detected account identifier into config.",
                    key=_k("fetch_user_btn"),
                ):
                    _setup_debug("Fetch User ID / Email button clicked.")
                    current_email = str(st.session_state.get("streamrip_form_email_or_userid", ""))
                    current_token = str(st.session_state.get("streamrip_form_password_or_token", ""))
                    current_app_id = str(st.session_state.get("streamrip_form_app_id", ""))
                    current_quality = int(st.session_state.get("streamrip_form_quality", default_rip_quality))
                    current_codec = str(st.session_state.get("streamrip_form_codec", default_codec))
                    current_downloads = str(
                        st.session_state.get(
                            "streamrip_form_downloads_folder",
                            st.session_state.streamrip_downloads_folder_draft,
                        )
                    )
                    current_downloads_db_path = str(
                        st.session_state.get("streamrip_form_downloads_db_path", "")
                    )
                    current_failed_downloads_path = str(
                        st.session_state.get("streamrip_form_failed_downloads_path", "")
                    )

                    token_for_lookup = current_token or env_qobuz_token
                    app_id_for_lookup = current_app_id or env_qobuz_app_id
                    ok_lookup, lookup_data, lookup_msg = fetch_qobuz_user_identifier(
                        app_id_for_lookup, token_for_lookup
                    )
                    if not ok_lookup:
                        _setup_debug(f"Fetch user identifier failed: {lookup_msg}")
                        _show_error(lookup_msg)
                    else:
                        save_ok, save_msg = save_streamrip_settings(
                            streamrip_config_path,
                            use_auth_token=True,
                            email_or_userid=str(lookup_data.get("identifier", current_email)),
                            password_or_token=token_for_lookup,
                            app_id=app_id_for_lookup,
                            quality=current_quality,
                            codec_selection=current_codec,
                            downloads_folder=current_downloads,
                            downloads_db_path=current_downloads_db_path,
                            failed_downloads_path=current_failed_downloads_path,
                        )
                        if save_ok:
                            _setup_debug("Fetched user identifier and saved config successfully.")
                            st.success(
                                f"{lookup_msg}: {lookup_data.get('identifier', '')}. "
                                "Saved to streamrip config."
                            )
                            st.rerun()
                        else:
                            _setup_debug(f"Saving fetched user identifier failed: {save_msg}")
                            _show_error(save_msg)
            with col_setup3:
                if st.button(
                    "Reload Streamrip Config",
                    help="Reloads Streamrip settings from config.toml and refreshes this setup panel.",
                    key=_k("reload_btn"),
                ):
                    _setup_debug("Reload Streamrip Config button clicked; rerunning app.")
                    st.rerun()

            if include_browser:
                _render_download_folder_browser()

            with st.form(_k("form")):
                st.write("Qobuz Credentials")
                use_auth_token_cfg = st.checkbox(
                    "Use auth token mode",
                    key=_k("use_auth_token"),
                )
                cred_col1, cred_col2 = st.columns(2)
                with cred_col1:
                    email_or_userid_cfg = st.text_input(
                        "Qobuz Email or User ID",
                        key=_k("email_or_userid"),
                    )
                with cred_col2:
                    password_or_token_cfg = st.text_input(
                        "Qobuz Password Hash or Auth Token",
                        type="password",
                        key=_k("password_or_token"),
                    )

                cred_row2_col1, cred_row2_col2 = st.columns(2)
                with cred_row2_col1:
                    app_id_cfg = st.text_input(
                        "Qobuz App ID",
                        key=_k("app_id"),
                    )
                with cred_row2_col2:
                    downloads_folder_cfg = st.text_input(
                        "Downloads Folder Path",
                        key=_k("downloads_folder_draft"),
                        help="Leave as-is if you do not want to change your current streamrip downloads folder.",
                    )
                path_row_col1, path_row_col2 = st.columns(2)
                with path_row_col1:
                    downloads_db_path_cfg = st.text_input(
                        "Downloads DB Path",
                        key=_k("downloads_db_path_draft"),
                        help="Defaults to `downloads.db` in the same folder as streamrip config.toml.",
                    )
                with path_row_col2:
                    failed_downloads_path_cfg = st.text_input(
                        "Failed Downloads Folder Path",
                        key=_k("failed_downloads_path_draft"),
                        help="Defaults to `failed/` in the same folder as streamrip config.toml.",
                    )

                st.write("Streamrip Defaults")
                defaults_col1, defaults_col2 = st.columns(2)
                quality_widget_key = _k("cfg_quality")
                if st.session_state.get(quality_widget_key) not in QUALITY_OPTIONS:
                    st.session_state[quality_widget_key] = default_rip_quality
                with defaults_col1:
                    cfg_quality = st.selectbox(
                        "Default Quality in streamrip config",
                        options=QUALITY_OPTIONS,
                        index=None,
                        placeholder="Choose quality",
                        format_func=format_quality_option,
                        key=quality_widget_key,
                    )
                codec_widget_key = _k("cfg_codec")
                if st.session_state.get(codec_widget_key) not in CODEC_OPTIONS:
                    st.session_state[codec_widget_key] = default_codec
                with defaults_col2:
                    cfg_codec = st.selectbox(
                        "Default Codec in streamrip config",
                        options=CODEC_OPTIONS,
                        index=None,
                        placeholder="Choose codec",
                        key=codec_widget_key,
                    )
                save_streamrip_btn = st.form_submit_button(
                    "Save Streamrip Config",
                    type="primary",
                    help="Writes all values in this form (credentials, downloads folder, quality, codec) to streamrip config.toml.",
                )

            if save_streamrip_btn:
                _setup_debug("Save Streamrip Config submitted.")
                downloads_folder_cfg = str(downloads_folder_cfg).strip()
                if not downloads_folder_cfg:
                    _setup_debug("Validation failed: downloads folder blank.")
                    _show_error("Downloads Folder Path cannot be blank.")
                    return
                normalized_downloads_path = os.path.abspath(os.path.expanduser(downloads_folder_cfg))
                if not os.path.isdir(normalized_downloads_path):
                    _setup_debug(f"Validation failed: downloads folder invalid `{normalized_downloads_path}`.")
                    _show_error(f"Downloads Folder Path is not a valid folder: `{normalized_downloads_path}`")
                    return
                downloads_db_path_cfg = str(downloads_db_path_cfg).strip()
                if not downloads_db_path_cfg:
                    _setup_debug("Validation failed: downloads DB path blank.")
                    _show_error("Downloads DB Path cannot be blank.")
                    return
                normalized_downloads_db_path = os.path.abspath(os.path.expanduser(downloads_db_path_cfg))
                try:
                    os.makedirs(os.path.dirname(normalized_downloads_db_path), exist_ok=True)
                except Exception as e:
                    _setup_debug(f"Failed creating Downloads DB parent directory: {e}")
                    _show_error(f"Could not create Downloads DB parent directory: {e}")
                    return
                failed_downloads_path_cfg = str(failed_downloads_path_cfg).strip()
                if not failed_downloads_path_cfg:
                    _setup_debug("Validation failed: failed downloads path blank.")
                    _show_error("Failed Downloads Folder Path cannot be blank.")
                    return
                normalized_failed_downloads_path = os.path.abspath(os.path.expanduser(failed_downloads_path_cfg))
                try:
                    os.makedirs(normalized_failed_downloads_path, exist_ok=True)
                except Exception as e:
                    _setup_debug(f"Failed creating failed downloads directory: {e}")
                    _show_error(f"Could not create Failed Downloads Folder Path: {e}")
                    return
                selected_quality = cfg_quality if cfg_quality is not None else default_rip_quality
                if selected_quality not in QUALITY_OPTIONS:
                    selected_quality = default_rip_quality
                selected_codec = cfg_codec if cfg_codec is not None else default_codec
                if selected_codec not in CODEC_OPTIONS:
                    selected_codec = default_codec
                ok, msg = save_streamrip_settings(
                    streamrip_config_path,
                    use_auth_token=use_auth_token_cfg,
                    email_or_userid=email_or_userid_cfg,
                    password_or_token=password_or_token_cfg,
                    app_id=app_id_cfg,
                    quality=selected_quality,
                    codec_selection=selected_codec,
                    downloads_folder=normalized_downloads_path,
                    downloads_db_path=normalized_downloads_db_path,
                    failed_downloads_path=normalized_failed_downloads_path,
                )
                if ok:
                    _setup_debug("Streamrip config save succeeded from setup form; syncing session state.")
                    st.session_state.streamrip_downloads_folder_persist = normalized_downloads_path
                    st.session_state.streamrip_downloads_folder_draft = normalized_downloads_path
                    st.session_state.streamrip_form_use_auth_token = bool(use_auth_token_cfg)
                    st.session_state.streamrip_form_email_or_userid = str(email_or_userid_cfg)
                    st.session_state.streamrip_form_password_or_token = str(password_or_token_cfg)
                    st.session_state.streamrip_form_app_id = str(app_id_cfg)
                    st.session_state.streamrip_form_downloads_folder = normalized_downloads_path
                    st.session_state.streamrip_form_downloads_db_path = normalized_downloads_db_path
                    st.session_state.streamrip_form_failed_downloads_path = normalized_failed_downloads_path
                    st.session_state.streamrip_form_quality = selected_quality
                    st.session_state.streamrip_form_codec = selected_codec
                    st.success(msg)
                    st.rerun()
                else:
                    _setup_debug(f"Streamrip config save failed from setup form: {msg}")
                    _show_error(msg)

            with st.expander("Raw streamrip config", expanded=False):
                show_config_secrets = st.checkbox("Show secrets", value=False, key=_k("show_secrets"))
                if st.button("Load Raw Config", key=_k("load_raw_config")):
                    st.session_state[_k("show_raw_config_body")] = True
                if st.session_state.get(_k("show_raw_config_body"), False):
                    st.code(read_streamrip_config_text(streamrip_config_path, show_config_secrets), language="toml")

        if streamrip_needs_setup:
            st.warning(
                "Complete Streamrip setup before ripping: set Qobuz email/user ID, token/password, Downloads Folder Path, Downloads DB Path, and Failed Downloads Folder Path."
            )


def _render_download_folder_browser() -> None:
    _setup_debug("Rendering download folder browser.")
    with st.expander("Streamrip Download Folder Browser (optional)", expanded=False):
        browser_path = st.session_state.streamrip_browser_path
        if not os.path.isdir(browser_path):
            browser_path = os.path.expanduser("~")
            st.session_state.streamrip_browser_path = browser_path

        if "streamrip_browser_path_input" not in st.session_state:
            st.session_state.streamrip_browser_path_input = browser_path
        if "streamrip_browser_path_last_synced" not in st.session_state:
            st.session_state.streamrip_browser_path_last_synced = browser_path
        if "streamrip_nav_back" not in st.session_state:
            st.session_state.streamrip_nav_back = []
        if "streamrip_nav_forward" not in st.session_state:
            st.session_state.streamrip_nav_forward = []
        if "streamrip_last_click_path" not in st.session_state:
            st.session_state.streamrip_last_click_path = ""
        if "streamrip_last_click_ts" not in st.session_state:
            st.session_state.streamrip_last_click_ts = 0.0
        if "streamrip_new_folder_name" not in st.session_state:
            st.session_state.streamrip_new_folder_name = ""
        if "streamrip_browser_notice" not in st.session_state:
            st.session_state.streamrip_browser_notice = ""
        if "streamrip_path_input_pending" not in st.session_state:
            st.session_state.streamrip_path_input_pending = ""
        if "streamrip_path_submit_requested" not in st.session_state:
            st.session_state.streamrip_path_submit_requested = False
        if "streamrip_browser_entries_cache_path" not in st.session_state:
            st.session_state.streamrip_browser_entries_cache_path = ""
        if "streamrip_browser_entries_cache_data" not in st.session_state:
            st.session_state.streamrip_browser_entries_cache_data = []
        if "streamrip_browser_entries_cache_ts" not in st.session_state:
            st.session_state.streamrip_browser_entries_cache_ts = 0.0
        if "streamrip_browser_entries_refresh_requested" not in st.session_state:
            st.session_state.streamrip_browser_entries_refresh_requested = False

        def resolve_path_input(target_path: str, base_path: str) -> str:
            raw = (target_path or "").strip()
            if not raw:
                return os.path.abspath(base_path)
            expanded = os.path.expanduser(raw)
            if os.path.isabs(expanded):
                return os.path.abspath(expanded)
            return os.path.abspath(os.path.join(base_path, expanded))

        def navigate_to(target_path: str) -> bool:
            current_base = os.path.abspath(st.session_state.streamrip_browser_path)
            target_abs = resolve_path_input(target_path, current_base)
            if not os.path.isdir(target_abs):
                _setup_debug(f"Browser navigation failed; path not found `{target_abs}`.")
                return False
            current_abs = os.path.abspath(st.session_state.streamrip_browser_path)
            if target_abs == current_abs:
                return True
            back_stack = list(st.session_state.streamrip_nav_back)
            back_stack.append(current_abs)
            st.session_state.streamrip_nav_back = back_stack[-200:]
            st.session_state.streamrip_nav_forward = []
            st.session_state.streamrip_browser_path = target_abs
            st.session_state.streamrip_browser_entries_refresh_requested = True
            _setup_debug(f"Browser navigated to `{target_abs}`.")
            return True

        def clear_folder_selection() -> None:
            st.session_state.streamrip_folder_selection = ""
            st.session_state.streamrip_last_click_path = ""
            st.session_state.streamrip_last_click_ts = 0.0

        def mark_path_submit_requested() -> None:
            st.session_state.streamrip_path_submit_requested = True

        if st.session_state.streamrip_browser_path_last_synced != browser_path:
            st.session_state.streamrip_browser_path_input = browser_path
            st.session_state.streamrip_browser_path_last_synced = browser_path
        if st.session_state.streamrip_path_input_pending:
            st.session_state.streamrip_browser_path_input = str(st.session_state.streamrip_path_input_pending)
            st.session_state.streamrip_path_input_pending = ""

        nav_bar_col1, nav_bar_col2, nav_bar_col3, nav_bar_col4, nav_bar_col5, nav_bar_col6, nav_bar_col7 = st.columns(
            [0.5, 0.5, 0.55, 4.8, 0.6, 2.1, 0.6]
        )
        current_abs_path = os.path.abspath(st.session_state.streamrip_browser_path)
        parent_abs_path = os.path.dirname(current_abs_path.rstrip(os.sep)) or current_abs_path
        can_go_parent = parent_abs_path != current_abs_path
        with nav_bar_col1:
            nav_back_clicked = st.button(
                "◀",
                key="streamrip_nav_back_btn",
                disabled=(not bool(st.session_state.streamrip_nav_back) and not can_go_parent),
                help="Go back in folder history. If no history exists, goes to parent folder.",
            )
        with nav_bar_col2:
            nav_forward_clicked = st.button(
                "▶",
                key="streamrip_nav_forward_btn",
                disabled=not bool(st.session_state.streamrip_nav_forward),
                help="Go forward in folder history after you used Back.",
            )
        with nav_bar_col3:
            nav_home_clicked = st.button("⌂", key="streamrip_browser_home", help="Jump to your home folder.")
        with nav_bar_col4:
            st.text_input(
                "Path",
                key="streamrip_browser_path_input",
                label_visibility="collapsed",
                autocomplete="on",
                on_change=mark_path_submit_requested,
            )
        with nav_bar_col5:
            nav_go_clicked = st.button("Go", key="streamrip_browser_go", help="Open the folder path from the path field.")
        with nav_bar_col6:
            st.text_input(
                "New Folder Name",
                key="streamrip_new_folder_name",
                label_visibility="collapsed",
                placeholder="New folder",
            )
        with nav_bar_col7:
            create_folder_clicked = st.button("+", key="streamrip_create_folder_btn", help="Create a new folder in the current location.")

        typed_path = str(st.session_state.streamrip_browser_path_input).strip()
        expanded_typed = resolve_path_input(typed_path, browser_path)
        if os.path.isdir(expanded_typed):
            suggestion_base = expanded_typed
            suggestion_prefix = ""
        else:
            suggestion_base = os.path.dirname(expanded_typed)
            suggestion_prefix = os.path.basename(expanded_typed)
        autocomplete_options = []
        if suggestion_base and os.path.isdir(suggestion_base):
            try:
                with os.scandir(suggestion_base) as scan:
                    for entry in scan:
                        if entry.name.startswith("."):
                            continue
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if suggestion_prefix and not entry.name.lower().startswith(suggestion_prefix.lower()):
                            continue
                        autocomplete_options.append(entry.path)
            except Exception:
                autocomplete_options = []
        autocomplete_options = sorted(autocomplete_options, key=lambda p: os.path.basename(p).lower())[:30]

        def open_or_complete_path_input(show_warning: bool = True) -> bool:
            candidate = st.session_state.streamrip_browser_path_input.strip()
            if navigate_to(candidate):
                return True
            if len(autocomplete_options) == 1:
                completed = os.path.abspath(autocomplete_options[0])
                if os.path.isdir(completed):
                    st.session_state.streamrip_path_input_pending = os.path.join(completed, "")
                    return True
            if len(autocomplete_options) > 1 and suggestion_prefix:
                option_names = [os.path.basename(p) for p in autocomplete_options]
                common_part = os.path.commonprefix(option_names)
                if common_part and common_part.lower() != suggestion_prefix.lower():
                    st.session_state.streamrip_path_input_pending = os.path.join(suggestion_base, common_part)
                    st.session_state.streamrip_browser_notice = "Path auto-completed. Press Enter/Go again to open."
                    return True
            if show_warning:
                st.warning("Enter an existing folder path.")
            return False

        if nav_back_clicked:
            clear_folder_selection()
            if st.session_state.streamrip_nav_back:
                current_abs = os.path.abspath(st.session_state.streamrip_browser_path)
                back_stack = list(st.session_state.streamrip_nav_back)
                target_abs = back_stack.pop()
                forward_stack = list(st.session_state.streamrip_nav_forward)
                forward_stack.append(current_abs)
                st.session_state.streamrip_nav_back = back_stack
                st.session_state.streamrip_nav_forward = forward_stack[-200:]
                st.session_state.streamrip_browser_path = target_abs
                st.session_state.streamrip_browser_entries_refresh_requested = True
                st.rerun()
            parent = os.path.dirname(browser_path.rstrip(os.sep)) or browser_path
            if parent != browser_path:
                current_abs = os.path.abspath(st.session_state.streamrip_browser_path)
                parent_abs = os.path.abspath(parent)
                forward_stack = list(st.session_state.streamrip_nav_forward)
                forward_stack.append(current_abs)
                st.session_state.streamrip_nav_forward = forward_stack[-200:]
                st.session_state.streamrip_browser_path = parent_abs
                st.session_state.streamrip_browser_entries_refresh_requested = True
                st.rerun()

        if nav_forward_clicked and st.session_state.streamrip_nav_forward:
            clear_folder_selection()
            current_abs = os.path.abspath(st.session_state.streamrip_browser_path)
            forward_stack = list(st.session_state.streamrip_nav_forward)
            target_abs = forward_stack.pop()
            back_stack = list(st.session_state.streamrip_nav_back)
            back_stack.append(current_abs)
            st.session_state.streamrip_nav_forward = forward_stack
            st.session_state.streamrip_nav_back = back_stack[-200:]
            st.session_state.streamrip_browser_path = target_abs
            st.session_state.streamrip_browser_entries_refresh_requested = True
            st.rerun()

        if nav_home_clicked:
            clear_folder_selection()
            if navigate_to(os.path.expanduser("~")):
                st.rerun()

        if nav_go_clicked:
            clear_folder_selection()
            if open_or_complete_path_input(show_warning=True):
                st.rerun()

        if st.session_state.streamrip_path_submit_requested:
            st.session_state.streamrip_path_submit_requested = False
            clear_folder_selection()
            if open_or_complete_path_input(show_warning=False):
                st.rerun()

        if create_folder_clicked:
            clear_folder_selection()
            raw_name = str(st.session_state.streamrip_new_folder_name).strip()
            invalid_name = (
                not raw_name
                or raw_name in {".", ".."}
                or "/" in raw_name
                or "\\" in raw_name
            )
            if invalid_name:
                _setup_debug(f"Create folder rejected invalid name `{raw_name}`.")
                st.warning("Enter a valid folder name.")
            else:
                new_folder_path = os.path.join(browser_path, raw_name)
                if os.path.exists(new_folder_path):
                    _setup_debug(f"Create folder rejected existing path `{new_folder_path}`.")
                    st.session_state.auto_scroll_alerts_once = True
                    st.error(f"Folder already exists: `{raw_name}`")
                else:
                    try:
                        os.makedirs(new_folder_path, exist_ok=False)
                        _setup_debug(f"Created folder `{new_folder_path}` from browser.")
                        st.session_state.streamrip_browser_notice = f"Created folder `{raw_name}`."
                        if navigate_to(new_folder_path):
                            st.rerun()
                    except Exception as e:
                        _setup_debug(f"Create folder failed for `{new_folder_path}`: {e}")
                        st.session_state.auto_scroll_alerts_once = True
                        st.error(f"Could not create folder: {e}")

        if st.session_state.streamrip_browser_notice:
            st.success(st.session_state.streamrip_browser_notice)
            st.session_state.streamrip_browser_notice = ""

        if "streamrip_folder_selection" not in st.session_state:
            st.session_state.streamrip_folder_selection = ""
        selected_candidate = str(st.session_state.streamrip_folder_selection).strip()
        if selected_candidate and not os.path.isdir(selected_candidate):
            st.session_state.streamrip_folder_selection = ""

        cache_ttl_seconds = 60.0
        entries_cache_path = str(st.session_state.streamrip_browser_entries_cache_path)
        entries_cache_data = list(st.session_state.streamrip_browser_entries_cache_data)
        entries_cache_ts = float(st.session_state.streamrip_browser_entries_cache_ts)
        cache_is_fresh = (datetime.now(timezone.utc).timestamp() - entries_cache_ts) <= cache_ttl_seconds
        refresh_requested = bool(st.session_state.streamrip_browser_entries_refresh_requested)
        should_refresh_entries = (
            refresh_requested
            or entries_cache_path != browser_path
            or not cache_is_fresh
            or not entries_cache_data
        )
        if should_refresh_entries:
            entries = list_directory_entries(browser_path)
            st.session_state.streamrip_browser_entries_cache_path = browser_path
            st.session_state.streamrip_browser_entries_cache_data = entries
            st.session_state.streamrip_browser_entries_cache_ts = datetime.now(timezone.utc).timestamp()
            st.session_state.streamrip_browser_entries_refresh_requested = False
            _setup_debug(
                f"Browser entries refreshed for `{browser_path}` "
                f"(refresh_requested={refresh_requested}, cache_fresh={cache_is_fresh})."
            )
        else:
            entries = entries_cache_data
            _setup_debug(f"Browser entries served from cache for `{browser_path}` ({len(entries)} entries).")
        if not entries:
            st.markdown(
                "<div style='text-align:center; color:#8a8a8a; padding:48px 0; font-size:1.05rem;'>Empty</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Single click selects. Double click a folder name to open.")
            head_col1, head_col2, head_col3 = st.columns([6, 2, 1.5])
            with head_col1:
                st.caption("Name")
            with head_col2:
                st.caption("Modified")
            with head_col3:
                st.caption("Size")

            selected_folder_raw = str(st.session_state.streamrip_folder_selection).strip()
            selected_folder_abs = os.path.abspath(selected_folder_raw) if selected_folder_raw else ""
            selected_row_keys = [
                f"streamrip_entry_row_{idx}"
                for idx, entry in enumerate(entries[:220])
                if selected_folder_abs and entry["is_dir"] and os.path.abspath(str(entry["path"])) == selected_folder_abs
            ]
            if selected_row_keys:
                selector_css = ", ".join([f".st-key-{row_key} button" for row_key in selected_row_keys])
                st.markdown(
                    f"""
<style>
{selector_css} {{
  border: 2px solid #4c8dff !important;
  box-shadow: 0 0 0 1px rgba(76, 141, 255, 0.35) !important;
}}
</style>
""",
                    unsafe_allow_html=True,
                )
            st.markdown(
                """
<style>
[class*="st-key-streamrip_file_row_"] button {
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  text-align: left !important;
  color: inherit !important;
  padding: 0 !important;
  min-height: 1.3rem !important;
}
[class*="st-key-streamrip_file_row_"] button:hover {
  background: rgba(120,120,120,0.10) !important;
}
.st-key-streamrip_deselect_space button {
  width: 100% !important;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  min-height: 44px !important;
}
</style>
""",
                unsafe_allow_html=True,
            )

            for idx, entry in enumerate(entries[:220]):
                row_col1, row_col2, row_col3 = st.columns([6, 2, 1.5])
                if entry["is_dir"]:
                    with row_col1:
                        if st.button(
                            f"📁 {entry['name']}",
                            key=f"streamrip_entry_row_{idx}",
                            help="Single-click selects this folder. Double-click quickly to open it.",
                        ):
                            now_ts = datetime.now(timezone.utc).timestamp()
                            clicked_path = str(entry["path"])
                            last_path = str(st.session_state.streamrip_last_click_path)
                            last_ts = float(st.session_state.streamrip_last_click_ts)
                            st.session_state.streamrip_folder_selection = clicked_path
                            if last_path == clicked_path and (now_ts - last_ts) <= 0.75:
                                if navigate_to(clicked_path):
                                    st.session_state.streamrip_last_click_path = ""
                                    st.session_state.streamrip_last_click_ts = 0.0
                                    st.rerun()
                            else:
                                st.session_state.streamrip_last_click_path = clicked_path
                                st.session_state.streamrip_last_click_ts = now_ts
                                st.rerun()
                    with row_col2:
                        st.caption(str(entry["modified"]))
                    with row_col3:
                        st.caption("-")
                else:
                    with row_col1:
                        if st.button(
                            f"📄 {entry['name']}",
                            key=f"streamrip_file_row_{idx}",
                            help="Click outside folder rows to clear folder selection.",
                        ):
                            clear_folder_selection()
                            st.rerun()
                    with row_col2:
                        st.caption(str(entry["modified"]))
                    with row_col3:
                        st.caption(f"{int(entry['size']):,} B")

            if st.button(" ", key="streamrip_deselect_space", help="Click empty area to clear folder selection."):
                clear_folder_selection()
                st.rerun()

        _footer_spacer, footer_clear_col, footer_button_col = st.columns([4.5, 1.5, 2])
        with footer_clear_col:
            if st.button(
                "Clear Selection",
                key="streamrip_clear_selection_btn",
                type="secondary",
                help="Clear selected folder outline.",
            ):
                clear_folder_selection()
                st.rerun()
        with footer_button_col:
            selected_candidate = str(st.session_state.streamrip_folder_selection).strip()
            selected_is_valid = bool(selected_candidate) and os.path.isdir(selected_candidate)
            selected_abs = os.path.abspath(selected_candidate) if selected_is_valid else ""
            current_abs = os.path.abspath(st.session_state.streamrip_browser_path)
            use_selected_mode = bool(selected_is_valid and selected_abs != current_abs)
            use_btn_label = (
                "Use Selected Folder"
                if use_selected_mode
                else "Use Current Folder"
            )
            if st.button(
                use_btn_label,
                key="streamrip_use_selected_folder_bottom",
                type="secondary",
                help="Sets Streamrip Downloads Folder Path. Click 'Save Streamrip Config' to write it to streamrip config.toml.",
            ):
                selected_path = os.path.abspath(str(st.session_state.streamrip_folder_selection))
                if not os.path.isdir(selected_path):
                    selected_path = os.path.abspath(st.session_state.streamrip_browser_path)
                st.session_state.streamrip_downloads_folder_draft = selected_path
                st.session_state.streamrip_downloads_folder_persist = selected_path
                clear_folder_selection()
                st.session_state.streamrip_nav_back = []
                st.session_state.streamrip_nav_forward = []
                st.session_state.streamrip_browser_notice = f"Downloads folder updated: `{selected_path}`"
                st.rerun()
