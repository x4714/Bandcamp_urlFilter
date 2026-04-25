from collections.abc import Callable

import streamlit as st

from app_modules.streamrip import CODEC_OPTIONS, QUALITY_OPTIONS, format_quality_option
from app_modules.ui_js import run_inline_script
from app_modules.ui_streamrip_setup import render_streamrip_setup


def render_streamrip_settings_tab(
    streamrip_config_init_msg: str,
    streamrip_settings_error: str,
    streamrip_needs_setup: bool,
    streamrip_config_path: str,
    streamrip_config_ready: bool,
    streamrip_settings: dict,
    default_rip_quality: int,
    default_codec: str,
    env_qobuz_app_id: str,
    env_qobuz_token: str,
    streamrip_missing_required_fields: list[str],
    on_rip_quality_change: Callable[[], None],
    app_debug: Callable[[str], None],
) -> None:
    st.subheader("⚙️ Streamrip Settings")
    if streamrip_config_init_msg:
        st.info(streamrip_config_init_msg)
    if streamrip_settings_error:
        st.warning(streamrip_settings_error)

    runtime_col1, runtime_col2 = st.columns(2)
    with runtime_col1:
        st.session_state.active_rip_quality = st.selectbox(
            "Rip Quality",
            options=QUALITY_OPTIONS,
            index=QUALITY_OPTIONS.index(st.session_state.active_rip_quality),
            format_func=format_quality_option,
            help="Runtime rip quality used by quick rip actions in tool tabs (equivalent to `--quality`). Also saved to streamrip config.",
            key="streamrip_runtime_rip_quality",
            on_change=on_rip_quality_change,
        )
        quality_save_result = st.session_state.pop("_quality_save_result", None)
        if quality_save_result is not None:
            quality_ok, quality_msg = quality_save_result
            if quality_ok:
                st.toast(quality_msg, icon="✅")
            else:
                st.warning(quality_msg)
    with runtime_col2:
        st.session_state.active_rip_codec = st.selectbox(
            "Rip Codec",
            options=CODEC_OPTIONS,
            index=CODEC_OPTIONS.index(st.session_state.active_rip_codec),
            help="Runtime codec used by quick rip actions in tool tabs (equivalent to `--codec`). Use Original for no conversion flag.",
            key="streamrip_runtime_rip_codec",
        )
    st.caption("Qobuz and Tidal ripping requires a premium subscription.")

    render_streamrip_setup(
        streamrip_needs_setup=streamrip_needs_setup,
        streamrip_config_path=streamrip_config_path,
        streamrip_config_ready=streamrip_config_ready,
        streamrip_settings=streamrip_settings,
        default_rip_quality=default_rip_quality,
        default_codec=default_codec,
        env_qobuz_app_id=env_qobuz_app_id,
        env_qobuz_token=env_qobuz_token,
        expanded_override=True,
        key_prefix="shared_streamrip_setup",
        include_browser=True,
        missing_required_fields=streamrip_missing_required_fields,
    )
    if st.session_state.streamrip_setup_attention_message:
        app_debug(f"Streamrip setup attention warning shown: {st.session_state.streamrip_setup_attention_message}")
        st.warning(st.session_state.streamrip_setup_attention_message)
        st.session_state.streamrip_setup_attention_message = ""
    if st.session_state.streamrip_setup_matcher_scroll_once:
        run_inline_script(
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
