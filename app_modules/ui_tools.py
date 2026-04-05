import os

import streamlit as st

from app_modules.streamrip import export_qobuz_batches, extract_qobuz_urls, run_streamrip_batches


def _read_text_upload(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    return uploaded_file.getvalue().decode("utf-8", errors="ignore")


def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def render_direct_qobuz_rip_tab(
    rip_quality: int,
    rip_codec: str,
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
    uploaded_qobuz_file = st.file_uploader(
        "Or upload a Qobuz links file",
        type=["txt", "log"],
        key="direct_qobuz_upload",
        disabled=locked,
    )
    uploaded_text = _read_text_upload(uploaded_qobuz_file)
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
        disabled=locked,
    )
    if rip_direct_btn:
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

            def _update_live_log(log_path: str, tail_text: str) -> None:
                live_log_caption.caption(f"Live rip log: {log_path}")
                live_log_box.code(tail_text or "(waiting for streamrip output...)", language="text")

            with st.spinner("Running streamrip for parsed Qobuz links..."):
                success_count, total_urls, failures, log_path = run_streamrip_batches(
                    batch_files,
                    rip_quality,
                    rip_codec,
                    progress_callback=_update_live_log,
                )
            _update_live_log(log_path, _read_log_tail(log_path))
            st.session_state.direct_rip_last_log_path = log_path
            if failures:
                st.session_state.direct_rip_last_level = "error"
                st.session_state.direct_rip_last_message = (
                    f"Direct rip processed {total_urls} URL(s) with errors:\n" + "\n".join(failures)
                )
            else:
                st.session_state.direct_rip_last_level = "success"
                st.session_state.direct_rip_last_message = (
                    f"Direct rip finished for {success_count} batch file(s) / {total_urls} URL(s)."
                )
            st.rerun()

    if st.session_state.direct_rip_last_message:
        if st.session_state.direct_rip_last_level == "success":
            st.success(st.session_state.direct_rip_last_message)
        elif st.session_state.direct_rip_last_level == "error":
            st.error(st.session_state.direct_rip_last_message)
        else:
            st.info(st.session_state.direct_rip_last_message)
    if st.session_state.direct_rip_last_log_path and os.path.exists(st.session_state.direct_rip_last_log_path):
        st.caption(f"Last direct rip log: {st.session_state.direct_rip_last_log_path}")
        with open(st.session_state.direct_rip_last_log_path, "r", encoding="utf-8") as f:
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
