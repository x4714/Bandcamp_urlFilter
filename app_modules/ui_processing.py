import asyncio
import os
from io import StringIO

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from app_modules.filtering import build_filtered_entries, get_download_link
from app_modules.matching import process_batch
from app_modules.streamrip import export_qobuz_batches, run_streamrip_batches


def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def handle_process_submission(
    process_btn: bool,
    uploaded_file,
    filter_config: dict,
    start_date,
    end_date,
    dry_run: bool,
) -> None:
    if not process_btn:
        return

    if uploaded_file is None:
        st.error("Please upload a .txt or .log file first.")
        return

    st.session_state.cancel_requested = False
    st.session_state.process_complete = False
    st.session_state.export_done = False
    st.session_state.rip_last_level = ""
    st.session_state.rip_last_message = ""
    st.session_state.rip_last_log_path = ""
    st.session_state.results = []

    stringio = StringIO(uploaded_file.getvalue().decode("utf-8", errors="ignore"))
    lines = stringio.readlines()
    filtered_entries = build_filtered_entries(lines, filter_config, start_date, end_date)

    st.session_state.status_log = (
        f"Found {len(filtered_entries)} unique URLs matching your filters out of {len(lines)} total lines."
    )

    if not filtered_entries:
        st.warning("No URLs matched the filter criteria.")
        return

    if dry_run:
        st.info("Dry Run enabled. Qobuz matching skipped. Showing filtered URLs:")
        df_dry = pd.DataFrame(
            [
                {
                    "Bandcamp URL": e.url,
                    "Artist": e.artist,
                    "Title": e.title,
                    "Genre": e.genre,
                    "Tracks": e.track_count,
                    "Duration (min)": e.duration_min,
                }
                for e in filtered_entries
            ]
        )
        st.dataframe(
            df_dry,
            column_config={"Bandcamp URL": st.column_config.LinkColumn()},
            width="stretch",
        )
        bc_urls = "\n".join([e.url for e in filtered_entries if e.url])
        st.download_button(
            label="Download Filtered Bandcamp Links (.txt)",
            data=bc_urls,
            file_name="filtered_bandcamp_urls.txt",
            mime="text/plain",
        )
        return

    load_dotenv(override=True)
    if not os.getenv("QOBUZ_USER_AUTH_TOKEN"):
        st.error(
            "QOBUZ_USER_AUTH_TOKEN is missing. Add it in `.env`, then run again, or use Dry Run mode."
        )
        return

    st.session_state.pending_entries = filtered_entries
    st.session_state.total_entries = len(filtered_entries)
    st.session_state.current_index = 0
    st.session_state.processing = True
    st.rerun()


def run_processing_tick() -> None:
    if not st.session_state.processing:
        return

    st.write("### Status Log")
    st.text(st.session_state.status_log)

    total = st.session_state.total_entries
    completed = st.session_state.current_index
    if total > 0:
        st.progress(completed / total)

    if st.session_state.cancel_requested:
        st.session_state.processing = False
        st.session_state.process_complete = False
        matched_count = len([r for r in st.session_state.results if r["Qobuz Link"]])
        st.session_state.status_log = (
            f"Cancelled. We found {matched_count} out of {total} matches before stopping."
        )
    else:
        batch_size = 5
        start_idx = st.session_state.current_index
        end_idx = min(start_idx + batch_size, total)

        if start_idx < total:
            st.session_state.status_log = f"Processing {start_idx + 1} to {end_idx} of {total}..."
            batch = st.session_state.pending_entries[start_idx:end_idx]
            batch_rows = asyncio.run(process_batch(batch))
            st.session_state.results.extend(batch_rows)
            st.session_state.current_index = end_idx

        if st.session_state.current_index >= total:
            st.session_state.processing = False
            st.session_state.process_complete = True
            matched_count = len([r for r in st.session_state.results if r["Qobuz Link"]])
            st.session_state.status_log = f"Complete! We found {matched_count} out of {total} matches."

    st.rerun()


def render_status_log(dry_run: bool) -> None:
    if not dry_run and st.session_state.status_log:
        st.write("### Status Log")
        st.text(st.session_state.status_log)


def render_results_and_exports(
    dry_run: bool,
    rip_quality: int,
    rip_codec: str,
    auto_rip_after_export: bool,
    streamrip_needs_setup: bool = False,
) -> None:
    if dry_run or not st.session_state.results:
        return

    st.markdown("---")
    st.subheader("📊 Results")

    if st.session_state.processing:
        st.info("⏳ Processing in progress. Results are updating by batch.")
    elif not st.session_state.process_complete:
        st.warning("⚠️ Processing was cancelled or interrupted. Showing partial results.")
    else:
        st.success("✅ Processing complete.")

    df = pd.DataFrame(st.session_state.results)
    st.dataframe(
        df,
        column_config={
            "Bandcamp Link": st.column_config.LinkColumn("Bandcamp URL"),
            "Qobuz Link": st.column_config.LinkColumn("Qobuz URL"),
        },
        width="stretch",
    )

    matched_qobuz_urls = [r["Qobuz Link"] for r in st.session_state.results if r.get("Qobuz Link")]
    qobuz_strings = get_download_link([{"qobuz_url": url} for url in matched_qobuz_urls])
    if matched_qobuz_urls:
        st.download_button(
            label=f"Download Qobuz Links (.txt) - {len(matched_qobuz_urls)} match(es)",
            data=qobuz_strings + "\n",
            file_name="qobuz_exports.txt",
            mime="text/plain",
        )
    else:
        st.info("No matched Qobuz links yet to download as a `.txt` file.")

    st.markdown("---")
    st.subheader("💾 Local Export & Batch Generator")
    st.markdown("Export on the left, or rip this run's matched Qobuz results on the right.")

    col_exp1, col_exp2 = st.columns([1, 2])
    with col_exp1:
        max_links = st.number_input("Max links per file", min_value=1, value=10, step=1)
    with col_exp2:
        btn_col1, btn_col2, _btn_spacer = st.columns([1.2, 1.6, 1.8])
        with btn_col1:
            export_btn = st.button("Export to Local Disk", type="primary")
        with btn_col2:
            rip_this_run_btn = st.button("Rip This Run's Qobuz Results")

    if export_btn or rip_this_run_btn:
        try:
            valid_urls = [r["Qobuz Link"] for r in st.session_state.results if r["Qobuz Link"]]
            if not valid_urls:
                st.warning("No matched Qobuz links found in this run.")
            else:
                batch_files, total_batches = export_qobuz_batches(valid_urls, int(max_links), rip_quality, rip_codec)
                st.session_state.export_done = True

                if export_btn:
                    st.success(
                        f"Successfully created {total_batches} batch file(s) in `/exports/` and generated `run_rip.bat` and `run_rip.sh`."
                    )

                should_run_rip = bool(rip_this_run_btn or (export_btn and auto_rip_after_export))
                if should_run_rip:
                    if streamrip_needs_setup:
                        st.session_state.streamrip_setup_matcher_expand_once = True
                        st.session_state.streamrip_setup_matcher_scroll_once = True
                        st.session_state.streamrip_setup_attention_message = (
                            "Complete Streamrip setup before ripping this run."
                        )
                        st.rerun()

                    live_log_caption = st.empty()
                    live_log_box = st.empty()

                    def _update_live_log(log_path: str, tail_text: str) -> None:
                        live_log_caption.caption(f"Live rip log: {log_path}")
                        live_log_box.code(tail_text or "(waiting for streamrip output...)", language="text")

                    with st.spinner("Running streamrip for exported batches..."):
                        success_count, total_urls, failures, log_path = run_streamrip_batches(
                            batch_files,
                            rip_quality,
                            rip_codec,
                            progress_callback=_update_live_log,
                        )
                    _update_live_log(log_path, _read_log_tail(log_path))
                    st.session_state.rip_last_log_path = log_path
                    if failures:
                        st.session_state.rip_last_level = "error"
                        st.session_state.rip_last_message = (
                            f"Auto rip processed {total_urls} URL(s) with errors:\n" + "\n".join(failures)
                        )
                    else:
                        st.session_state.rip_last_level = "success"
                        st.session_state.rip_last_message = (
                            f"Rip finished for {success_count} batch file(s) / {total_urls} URL(s)."
                        )
                st.rerun()
        except Exception as e:
            st.error(f"Error during export/rip: {e}")

    if st.session_state.rip_last_message:
        if st.session_state.rip_last_level == "success":
            st.success(st.session_state.rip_last_message)
        elif st.session_state.rip_last_level == "error":
            st.error(st.session_state.rip_last_message)
        else:
            st.info(st.session_state.rip_last_message)
    if st.session_state.rip_last_log_path and os.path.exists(st.session_state.rip_last_log_path):
        st.caption(f"Last rip log: {st.session_state.rip_last_log_path}")
        with open(st.session_state.rip_last_log_path, "r", encoding="utf-8") as f:
            log_text = f.read()
        st.download_button(
            "Download Last Rip Log",
            data=log_text,
            file_name="streamrip_last.log",
            mime="text/plain",
        )
        st.text_area("Last Rip Log (tail)", value=log_text[-4000:], height=220)
