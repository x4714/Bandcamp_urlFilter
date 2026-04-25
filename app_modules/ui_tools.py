from __future__ import annotations

import os

import streamlit as st

from app_modules.debug_logging import emit_debug
from app_modules.streamrip import extract_qobuz_urls, run_streamrip_batches

UI_TOOLS_LOG_TAIL_CHARS = 6000
UI_TOOLS_LOG_PREVIEW_CHARS = 4000


def _ui_tools_debug(message: str) -> None:
    emit_debug("ui tools", message)


def _read_text_upload(uploaded_files) -> list[tuple[str, str]]:
    if not uploaded_files:
        return []
    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]
    return [(f.name, f.getvalue().decode("utf-8", errors="ignore")) for f in uploaded_files]


def _read_log_tail(log_path: str, max_chars: int = UI_TOOLS_LOG_TAIL_CHARS) -> str:
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def _build_direct_rip_batches(
    pasted_text: str,
    uploaded_qobuz_files,
) -> tuple[list[str], list[tuple[str, list[str]]]]:
    batch_map: dict[str, list[str]] = {}
    pasted_urls = extract_qobuz_urls(pasted_text)
    if pasted_urls:
        batch_map["qobuz_batch_pasted.txt"] = pasted_urls

    for fname, content in _read_text_upload(uploaded_qobuz_files):
        file_urls = extract_qobuz_urls(content)
        if not file_urls:
            continue
        batch_map.setdefault(fname, []).extend(file_urls)

    direct_urls: list[str] = []
    prepared_batches: list[tuple[str, list[str]]] = []
    seen_urls: set[str] = set()
    for fname, urls in batch_map.items():
        unique_urls_in_batch: list[str] = []
        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            unique_urls_in_batch.append(url)
            direct_urls.append(url)
        if unique_urls_in_batch:
            prepared_batches.append((fname, unique_urls_in_batch))
    return direct_urls, prepared_batches


def _write_direct_rip_batches(prepared_batches: list[tuple[str, list[str]]]) -> list[str]:
    export_dir = os.path.abspath("exports")
    os.makedirs(export_dir, exist_ok=True)

    written_files: list[str] = []
    for fname, urls in prepared_batches:
        filepath = os.path.join(export_dir, fname)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(urls) + "\n")
        written_files.append(fname)
    return written_files


def render_direct_qobuz_rip_tab(
    rip_quality: int,
    rip_codec: str,
    streamrip_needs_setup: bool = False,
    streamrip_missing_required_fields: list[str] | None = None,
    locked: bool = False,
) -> None:
    _ui_tools_debug(
        f"Rendering direct rip tab. locked={locked}, streamrip_needs_setup={streamrip_needs_setup}, "
        f"rip_quality={rip_quality}, rip_codec={rip_codec}."
    )
    st.subheader("🔗 Direct Qobuz Rip")
    st.caption("Paste Qobuz links or upload a `.txt/.log` file, then rip directly with streamrip.")
    missing_required_fields = list(streamrip_missing_required_fields or [])
    missing_labels = {
        "email_or_userid": "Qobuz Email or User ID",
        "password_or_token": "Qobuz Password Hash or Auth Token",
        "downloads_folder": "Downloads Folder Path",
        "downloads_db_path": "Downloads DB Path",
        "failed_downloads_path": "Failed Downloads Folder Path",
    }
    if streamrip_needs_setup:
        labels = [missing_labels.get(f, f.replace("_", " ").title()) for f in missing_required_fields]
        if labels:
            st.warning("Actions in this tab are disabled. Missing settings: " + ", ".join(labels))
        else:
            st.warning("Actions in this tab are disabled until Streamrip setup is complete.")
        if st.button("Open Streamrip Settings Tab", key="direct_open_streamrip_settings"):
            if missing_required_fields:
                st.session_state.streamrip_setup_focus_field = missing_required_fields[0]
            st.session_state.main_tab_selection_pending = "Streamrip Settings"
            st.session_state.streamrip_setup_attention_message = "Finish the missing Streamrip settings to enable direct ripping."
            st.rerun()

    if "direct_rip_last_level" not in st.session_state:
        st.session_state.direct_rip_last_level = ""
    if "direct_rip_last_message" not in st.session_state:
        st.session_state.direct_rip_last_message = ""
    if "direct_rip_last_log_path" not in st.session_state:
        st.session_state.direct_rip_last_log_path = ""

    pasted_text = st.text_area(
        "Paste Qobuz Links",
        key="direct_qobuz_paste_text",
        height=180,
        placeholder="https://www.qobuz.com/...\nhttps://play.qobuz.com/...",
        disabled=locked,
    )
    uploaded_qobuz_files = st.file_uploader(
        "Or upload Qobuz links file(s)",
        type=["txt", "log"],
        key="direct_qobuz_upload",
        accept_multiple_files=True,
        disabled=locked,
    )
    direct_urls, prepared_batches = _build_direct_rip_batches(pasted_text, uploaded_qobuz_files)
    _ui_tools_debug(f"Parsed {len(direct_urls)} direct Qobuz URL(s) from input.")
    st.caption(f"Detected {len(direct_urls)} unique Qobuz URL(s).")
    if direct_urls:
        st.download_button(
            "Download Parsed Qobuz Links (.txt)",
            data="\n".join(direct_urls) + "\n",
            file_name="qobuz_direct_rip_input.txt",
            mime="text/plain",
            key="direct_qobuz_download_parsed",
            disabled=locked,
        )

    rip_direct_btn = st.button(
        "Rip Parsed Qobuz Links",
        type="primary",
        key="direct_qobuz_rip_btn",
        help=(
            "Disabled until required Streamrip settings are completed."
            if streamrip_needs_setup
            else "Run Streamrip for all parsed Qobuz links."
        ),
        disabled=locked or streamrip_needs_setup,
    )
    if rip_direct_btn:
        _ui_tools_debug("Direct rip button clicked.")
        if streamrip_needs_setup:
            _ui_tools_debug("Direct rip blocked because streamrip setup is incomplete.")
            st.session_state.streamrip_setup_matcher_expand_once = True
            st.session_state.streamrip_setup_matcher_scroll_once = True
            st.session_state.streamrip_setup_attention_message = (
                "Complete Streamrip setup before ripping: Qobuz credentials, Downloads Folder Path, Downloads DB Path, and Failed Downloads Folder Path are required."
            )
            st.rerun()
        if not direct_urls:
            _ui_tools_debug("Direct rip blocked because no URLs were detected.")
            st.warning("No Qobuz links detected. Paste links or upload a file first.")
        else:
            final_batch_files = _write_direct_rip_batches(prepared_batches)
            total_batches = len(final_batch_files)
            _ui_tools_debug(f"Starting direct rip run for {len(direct_urls)} URL(s).")
            st.info(f"Prepared {total_batches} batch file(s) in `/exports/`. Starting streamrip...")

            live_log_caption = st.empty()
            live_log_box = st.empty()
            rip_progress_caption = st.empty()
            rip_progress_bar = st.progress(0.0)

            def _update_live_log(log_path: str, tail_text: str) -> None:
                live_log_caption.caption(f"Live rip log: {log_path}")
                live_log_box.code(tail_text or "(waiting for streamrip output...)", language="text")

            def _update_rip_status(done: int, total: int, message: str) -> None:
                normalized_total = max(int(total), 1)
                normalized_done = min(max(int(done), 0), normalized_total)
                rip_progress_bar.progress(float(normalized_done) / float(normalized_total))
                rip_progress_caption.caption(message)

            with st.spinner("Running streamrip for parsed Qobuz links..."):
                success_count, total_urls, failures, skipped, successes, log_path = run_streamrip_batches(
                    final_batch_files,
                    rip_quality,
                    rip_codec,
                    progress_callback=_update_live_log,
                    status_callback=_update_rip_status,
                )
            _update_live_log(log_path, _read_log_tail(log_path))
            _update_rip_status(total_urls, total_urls, "Streamrip run finished.")
            st.session_state.direct_rip_last_log_path = log_path
            if failures or skipped or successes:
                if failures:
                    _ui_tools_debug(f"Direct rip finished with {len(failures)} failure(s).")
                if skipped:
                    _ui_tools_debug(f"Direct rip reported {len(skipped)} skipped URL(s).")
                if successes:
                    _ui_tools_debug(f"Direct rip reported {len(successes)} success(es).")
                st.session_state.direct_rip_last_level = "warning" if failures else "success"
                st.session_state.direct_rip_last_failures = failures
                st.session_state.direct_rip_last_skipped = skipped
                st.session_state.direct_rip_last_successes = successes
                st.session_state.direct_rip_last_message = (
                    f"Direct rip processed {total_urls} URL(s). See results below:"
                )
            else:
                _ui_tools_debug("Direct rip finished successfully without failures.")
                st.session_state.direct_rip_last_level = "success"
                st.session_state.direct_rip_last_failures = []
                st.session_state.direct_rip_last_skipped = []
                st.session_state.direct_rip_last_message = (
                    f"Direct rip finished for {success_count} batch file(s) / {total_urls} URL(s)."
                )
            st.rerun()

    if st.session_state.direct_rip_last_message:
        if st.session_state.direct_rip_last_level == "success":
            st.success(st.session_state.direct_rip_last_message)
        elif st.session_state.direct_rip_last_level == "error":
            st.session_state.auto_scroll_alerts_once = True
            st.error(st.session_state.direct_rip_last_message)
        elif st.session_state.direct_rip_last_level == "warning":
            st.session_state.auto_scroll_alerts_once = True
            st.warning(st.session_state.direct_rip_last_message)
        else:
            st.info(st.session_state.direct_rip_last_message)
            
        _failed_list = st.session_state.get("direct_rip_last_failures", [])
        _skipped_list = st.session_state.get("direct_rip_last_skipped", [])
        _success_list = st.session_state.get("direct_rip_last_successes", [])
        if _failed_list or _skipped_list or _success_list:
            import pandas as pd
            if _success_list:
                st.write("**✅ Newly Downloaded / Loaded**")
                df_success = pd.DataFrame(_success_list)
                st.dataframe(df_success, column_config={"URL": st.column_config.LinkColumn()}, width="stretch")
            if _failed_list:
                st.write("**⚠️ Errors**")
                df_failures = pd.DataFrame(_failed_list)
                st.dataframe(df_failures, column_config={"URL": st.column_config.LinkColumn()}, width="stretch")
            if _skipped_list:
                st.write("**⏭️ Skipped**")
                df_skipped = pd.DataFrame(_skipped_list)
                st.dataframe(df_skipped, column_config={"URL": st.column_config.LinkColumn()}, width="stretch")
    if st.session_state.direct_rip_last_log_path and os.path.exists(st.session_state.direct_rip_last_log_path):
        st.caption(f"Last direct rip log: {st.session_state.direct_rip_last_log_path}")
        with open(st.session_state.direct_rip_last_log_path, "r", encoding="utf-8", errors="replace") as f:
            log_text = f.read()
        st.download_button(
            "Download Direct Rip Log",
            data=log_text,
            file_name="streamrip_direct_last.log",
            mime="text/plain",
            key="direct_qobuz_log_download",
            disabled=locked,
        )
        st.text_area(
            "Direct Rip Log (tail)",
            value=log_text[-UI_TOOLS_LOG_PREVIEW_CHARS:],
            height=220,
            key="direct_qobuz_log_tail",
            disabled=locked,
        )
