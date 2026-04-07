import os

import streamlit as st

from app_modules.streamrip import export_qobuz_batches, extract_qobuz_urls, run_streamrip_batches


def _read_text_upload(uploaded_files) -> str:
    if not uploaded_files:
        return ""
    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]
    return "\n".join(f.getvalue().decode("utf-8", errors="ignore") for f in uploaded_files)


def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def render_direct_qobuz_rip_tab(
    rip_quality: int,
    rip_codec: str,
    streamrip_needs_setup: bool = False,
    locked: bool = False,
) -> None:
    st.subheader("🔗 Direct Qobuz Rip")
    st.caption("Paste Qobuz links or upload a `.txt/.log` file, then rip directly with streamrip.")

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
    uploaded_text = _read_text_upload(uploaded_qobuz_files)
    merged_text = f"{pasted_text}\n{uploaded_text}".strip()
    direct_urls = extract_qobuz_urls(merged_text)

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
        disabled=locked or streamrip_needs_setup,
    )
    if rip_direct_btn:
        if streamrip_needs_setup:
            st.session_state.streamrip_setup_matcher_expand_once = True
            st.session_state.streamrip_setup_matcher_scroll_once = True
            st.session_state.streamrip_setup_attention_message = (
                "Complete Streamrip setup before ripping: Qobuz credentials, Downloads Folder Path, Downloads DB Path, and Failed Downloads Folder Path are required."
            )
            st.rerun()
        if not direct_urls:
            st.warning("No Qobuz links detected. Paste links or upload a file first.")
        else:
            batch_files, total_batches = export_qobuz_batches(
                direct_urls,
                max(1, len(direct_urls)),
                rip_quality,
                rip_codec,
            )
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
                success_count, total_urls, failures, skipped, log_path = run_streamrip_batches(
                    batch_files,
                    rip_quality,
                    rip_codec,
                    progress_callback=_update_live_log,
                    status_callback=_update_rip_status,
                )
            _update_live_log(log_path, _read_log_tail(log_path))
            _update_rip_status(total_urls, total_urls, "Streamrip run finished.")
            st.session_state.direct_rip_last_log_path = log_path
            
            if failures or skipped:
                st.session_state.direct_rip_last_level = "warning" if failures else "success"
                st.session_state.direct_rip_last_failures = failures
                st.session_state.direct_rip_last_skipped = skipped
                st.session_state.direct_rip_last_message = (
                    f"Direct rip processed {total_urls} URL(s). See results below:"
                )
            else:
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
        if _failed_list or _skipped_list:
            import pandas as pd
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
            value=log_text[-4000:],
            height=220,
            key="direct_qobuz_log_tail",
            disabled=locked,
        )
