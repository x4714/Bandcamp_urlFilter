import asyncio
import os
import sys
from datetime import datetime, timezone
from io import StringIO
from typing import Optional

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from app_modules.debug_logging import emit_debug
from app_modules.filtering import build_filtered_entries, get_download_link
from app_modules.matching import process_batch, process_single_entry
from app_modules.streamrip import export_qobuz_batches, run_streamrip_batches
from logic.gazelle_api import GazelleAPI


def _ui_processing_debug(message: str) -> None:
    emit_debug("ui processing", message)


def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
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
    _ui_processing_debug("Process submission triggered.")

    if uploaded_file is None:
        _ui_processing_debug("Process blocked: no file uploaded.")
        st.session_state.auto_scroll_alerts_once = True
        st.error("Please upload a .txt or .log file first.")
        return

    st.session_state.cancel_requested = False
    st.session_state.process_complete = False
    st.session_state.export_done = False
    st.session_state.rip_last_level = ""
    st.session_state.rip_last_message = ""
    st.session_state.rip_last_log_path = ""
    st.session_state.results = []
    st.session_state.is_dry_run_run = False
    st.session_state.dry_run_results = []

    stringio = StringIO(uploaded_file.getvalue().decode("utf-8", errors="ignore"))
    lines = stringio.readlines()
    filtered_entries = build_filtered_entries(lines, filter_config, start_date, end_date)
    _ui_processing_debug(
        f"Loaded {len(lines)} line(s); filtered down to {len(filtered_entries)} unique entry(ies). "
        f"dry_run={dry_run}"
    )

    st.session_state.status_log = (
        f"Found {len(filtered_entries)} unique URLs matching your filters out of {len(lines)} total lines."
    )

    if not filtered_entries:
        _ui_processing_debug("No entries matched filters; stopping submission flow.")
        st.warning("No URLs matched the filter criteria.")
        return

    if dry_run:
        st.session_state.is_dry_run_run = True
        st.session_state.dry_run_results = filtered_entries
        st.session_state.process_complete = True
        _ui_processing_debug("Dry run mode enabled; stored filtered entries and rerunning UI.")
        st.rerun()

    load_dotenv(override=True)
    if not os.getenv("QOBUZ_USER_AUTH_TOKEN"):
        _ui_processing_debug("Process blocked: QOBUZ_USER_AUTH_TOKEN missing in env.")
        st.session_state.auto_scroll_alerts_once = True
        st.error(
            "QOBUZ_USER_AUTH_TOKEN is missing. Add it in `.env`, then run again, or use Dry Run mode."
        )
        return

    st.session_state.pending_entries = filtered_entries
    st.session_state.total_entries = len(filtered_entries)
    st.session_state.current_index = 0
    st.session_state.processing = True
    st.session_state.check_red = filter_config.get("check_red", False)
    st.session_state.check_ops = filter_config.get("check_ops", False)
    
    # Initialize trackers if needed
    st.session_state.batch_trackers = []
    if st.session_state.check_red or st.session_state.check_ops:
        red_key = os.getenv("RED_API_KEY", "")
        ops_key = os.getenv("OPS_API_KEY", "")
        red_url = os.getenv("RED_URL", "https://redacted.sh").rstrip("/")
        ops_url = os.getenv("OPS_URL", "https://orpheus.network").rstrip("/")
        
        if st.session_state.check_red and red_key:
            st.session_state.batch_trackers.append(GazelleAPI("RED", red_url, api_key=red_key))
        if st.session_state.check_ops and ops_key:
            st.session_state.batch_trackers.append(GazelleAPI("OPS", ops_url, api_key=ops_key))

    _ui_processing_debug(f"Queued {len(filtered_entries)} entries for async matching run. Trackers: {len(st.session_state.batch_trackers)}")
    st.rerun()


def run_processing_tick() -> None:
    if not st.session_state.processing:
        return
    _ui_processing_debug("Processing tick started.")

    total = st.session_state.total_entries
    completed = st.session_state.current_index
    matched_so_far = len([r for r in st.session_state.results if r.get("Qobuz Link")])
    errors_so_far = len([r for r in st.session_state.results if str(r.get("Status", "")).startswith("⚠️")])
    status_box = st.empty()
    progress_box = st.empty()
    detail_box = st.empty()
    status_box.info(st.session_state.status_log)
    if total > 0:
        progress_box.progress(completed / total, text=f"Processed {completed}/{total}")
    detail_box.caption(
        f"Matched so far: {matched_so_far} | Errors so far: {errors_so_far} | Remaining: {max(total - completed, 0)}"
    )

    if st.session_state.cancel_requested:
        _ui_processing_debug("Cancellation requested; ending processing loop.")
        st.session_state.processing = False
        st.session_state.process_complete = False
        
        matched_count = len([r for r in st.session_state.results if r["Qobuz Link"]])
        detail_box.caption(
            f"Current: Stopped | Matches found: {matched_count}"
        )
        st.session_state.status_log = (
            f"Cancelled. We found {matched_count} out of {total} matches before stopping."
        )
    else:
        batch_size = 5
        start_idx = st.session_state.current_index
        end_idx = min(start_idx + batch_size, total)

        if start_idx < total:
            _ui_processing_debug(f"Processing batch slice {start_idx}:{end_idx} of {total}.")
            st.session_state.status_log = f"Processing {start_idx + 1} to {end_idx} of {total}..."
            status_box.info(st.session_state.status_log)
            batch = st.session_state.pending_entries[start_idx:end_idx]

            def _on_batch_progress(done: int, batch_total: int, row: dict) -> None:
                global_done = start_idx + done
                album = str(row.get("Album", "") or row.get("Bandcamp Link", "") or "").strip()
                status_text = str(row.get("Status", "")).strip() or "Working"
                progress_fraction = (global_done / total) if total > 0 else 0.0
                progress_box.progress(progress_fraction, text=f"Processed {global_done}/{total}")
                detail_box.caption(
                    f"Current: {status_text} | {album[:120]}"
                )

            check_red_flag = st.session_state.get("check_red", False)
            check_ops_flag = st.session_state.get("check_ops", False)
            batch_trackers = st.session_state.get("batch_trackers", [])
            batch_rows = asyncio.run(process_batch(
                batch, 
                progress_callback=_on_batch_progress, 
                check_dupes=(check_red_flag or check_ops_flag),
                existing_trackers=batch_trackers
            ))
            st.session_state.results.extend(batch_rows)
            st.session_state.current_index = end_idx
            _ui_processing_debug(
                f"Batch processed. added_rows={len(batch_rows)}, current_index={st.session_state.current_index}."
            )
            matched_so_far = len([r for r in st.session_state.results if r.get("Qobuz Link")])
            errors_so_far = len([r for r in st.session_state.results if str(r.get("Status", "")).startswith("⚠️")])
            detail_box.caption(
                f"Matched so far: {matched_so_far} | Errors so far: {errors_so_far} | Remaining: {max(total - end_idx, 0)}"
            )

        if st.session_state.current_index >= total:
            _ui_processing_debug("All pending entries processed; marking run complete.")
            st.session_state.processing = False
            st.session_state.process_complete = True
            st.session_state.batch_trackers = []

            matched_count = len([r for r in st.session_state.results if r["Qobuz Link"]])
            st.session_state.status_log = f"Complete! We found {matched_count} out of {total} matches."
            status_box.success(st.session_state.status_log)
            if total > 0:
                progress_box.progress(1.0, text=f"Processed {total}/{total}")
            detail_box.caption(
                f"Matched total: {matched_count} | Not matched: {max(total - matched_count, 0)}"
            )

    st.rerun()


def render_status_log(dry_run: bool) -> None:
    if not dry_run and st.session_state.status_log:
        _ui_processing_debug("Rendering status log block.")
        st.write("### Status Log")
        st.text(st.session_state.status_log)


def render_results_and_exports(
    dry_run: bool,
    rip_quality: int,
    rip_codec: str,
    auto_rip_after_export: bool,
    streamrip_needs_setup: bool = False,
    streamrip_missing_required_fields: list[str] | None = None,
) -> None:
    if st.session_state.is_dry_run_run:
        st.markdown("---")
        st.subheader("📊 Dry Run Filtered URLs")
        st.info("Dry Run was enabled. Qobuz matching skipped. Showing filtered URLs from Bandcamp:")
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
                for e in st.session_state.dry_run_results
            ]
        )
        st.dataframe(
            df_dry,
            column_config={"Bandcamp URL": st.column_config.LinkColumn()},
            width="stretch",
        )
        bc_urls = "\n".join([e.url for e in st.session_state.dry_run_results if e.url])
        st.download_button(
            label="Download Filtered Bandcamp Links (.txt)",
            data=bc_urls,
            file_name="filtered_bandcamp_urls.txt",
            mime="text/plain",
        )
        return

    if not st.session_state.results:
        return
    _ui_processing_debug(
        f"Rendering results/exports section. results={len(st.session_state.results)}, "
        f"auto_rip_after_export={auto_rip_after_export}, streamrip_needs_setup={streamrip_needs_setup}."
    )

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

    # Check for manual dupe re-check
    red_key = os.getenv("RED_API_KEY", "")
    ops_key = os.getenv("OPS_API_KEY", "")
    
    if red_key or ops_key:
        if st.button("Check Results for Dupes (RED/OPS)"):
            with st.status("Checking existing results for duplicates...") as status:
                # Initialize trackers
                trackers = []
                red_url = os.getenv("RED_URL", "https://redacted.sh").rstrip("/")
                ops_url = os.getenv("OPS_URL", "https://orpheus.network").rstrip("/")
                if red_key:
                    trackers.append(GazelleAPI("RED", red_url, api_key=red_key))
                if ops_key:
                    trackers.append(GazelleAPI("OPS", ops_url, api_key=ops_key))
                
                if not trackers:
                    st.warning("No tracker credentials found in .env.")
                else:
                    async def run_manual_check():
                        new_results = []
                        try:
                            for idx, res in enumerate(st.session_state.results):
                                if res.get("Qobuz Link") and "Dupe" not in str(res.get("Status", "")):
                                    artist = res.get("Artist")
                                    album = res.get("Album")
                                    upc = res.get("UPC") 
                                    
                                    status.update(label=f"Checking {idx+1}/{len(st.session_state.results)}: {artist} - {album}...")
                                    
                                    tracker_results = []
                                    for tracker in trackers:
                                        is_dupe, info = await tracker.search_duplicates(artist, album, upc=upc)
                                        if info:
                                            # info now contains descriptive messages like "Dupe (UPC) @ RED"
                                            tracker_results.append(info)
                                    
                                    if tracker_results:
                                        res["Status"] = str(res.get("Status", "✅ Matched")) + " | " + " | ".join(tracker_results)
                                new_results.append(res)
                            st.session_state.results = new_results
                        except Exception as e:
                            st.error(f"Error during manual check: {e}")

                    asyncio.run(run_manual_check())
                    status.update(label="Dupe check complete.", state="complete")
                    st.rerun()

    valid_export_results = [r for r in st.session_state.results if r.get("Qobuz Link") and "Dupe (" not in str(r.get("Status", ""))]
    matched_qobuz_urls = [r["Qobuz Link"] for r in valid_export_results]
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
    missing_required_fields = list(streamrip_missing_required_fields or [])
    missing_labels = {
        "email_or_userid": "Qobuz Email or User ID",
        "password_or_token": "Qobuz Password Hash or Auth Token",
        "downloads_folder": "Downloads Folder Path",
        "downloads_db_path": "Downloads DB Path",
        "failed_downloads_path": "Failed Downloads Folder Path",
    }

    col_exp1, col_exp2 = st.columns([1, 2])
    with col_exp1:
        max_links = st.number_input("Max links per file", min_value=1, value=10, step=1)
    with col_exp2:
        btn_col1, btn_col2, _btn_spacer = st.columns([1.2, 1.6, 1.8])
        with btn_col1:
            export_btn = st.button("Export to Local Disk", type="primary")
        with btn_col2:
            rip_this_run_btn = st.button(
                "Rip This Run's Qobuz Results",
                disabled=streamrip_needs_setup,
                help=(
                    "Disabled until required Streamrip settings are completed."
                    if streamrip_needs_setup
                    else "Run Streamrip immediately for this run's exported URLs."
                ),
            )

    if streamrip_needs_setup:
        labels = [missing_labels.get(f, f.replace("_", " ").title()) for f in missing_required_fields]
        if labels:
            st.warning("Rip is disabled. Missing settings: " + ", ".join(labels))
        else:
            st.warning("Rip is disabled. Streamrip setup is incomplete.")
        if st.button("Open Streamrip Settings Tab", key="matcher_open_streamrip_settings"):
            if missing_required_fields:
                st.session_state.streamrip_setup_focus_field = missing_required_fields[0]
            st.session_state.main_tab_selection_pending = "Streamrip Settings"
            st.session_state.streamrip_setup_attention_message = "Finish the missing Streamrip settings to enable ripping."
            st.rerun()

    if export_btn or rip_this_run_btn:
        _ui_processing_debug(
            f"Export/rip action clicked. export_btn={export_btn}, rip_this_run_btn={rip_this_run_btn}."
        )
        try:
            valid_urls = [r["Qobuz Link"] for r in st.session_state.results if r.get("Qobuz Link") and "Dupe (" not in str(r.get("Status", ""))]
            if not valid_urls:
                _ui_processing_debug("Export/rip action had no matched Qobuz URLs.")
                st.warning("No matched Qobuz links found in this run.")
            else:
                _ui_processing_debug(
                    f"Exporting {len(valid_urls)} URL(s) with max_links={int(max_links)}."
                )
                batch_files, total_batches = export_qobuz_batches(valid_urls, int(max_links), rip_quality, rip_codec)
                st.session_state.export_done = True

                if export_btn:
                    st.success(
                        f"Successfully created {total_batches} batch file(s) in `/exports/` and generated `run_rip.bat` and `run_rip.sh`."
                    )

                should_run_rip = bool(rip_this_run_btn or (export_btn and auto_rip_after_export))
                if should_run_rip:
                    if streamrip_needs_setup:
                        _ui_processing_debug("Auto/manual rip blocked because streamrip setup is incomplete.")
                        st.session_state.streamrip_setup_matcher_expand_once = True
                        st.session_state.streamrip_setup_matcher_scroll_once = True
                        st.session_state.streamrip_setup_attention_message = (
                            "Complete Streamrip setup before ripping this run."
                        )
                        st.rerun()

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

                    with st.spinner("Running streamrip for exported batches..."):
                        success_count, total_urls, failures, skipped, successes, log_path = run_streamrip_batches(
                            batch_files,
                            rip_quality,
                            rip_codec,
                            progress_callback=_update_live_log,
                            status_callback=_update_rip_status,
                        )
                    _update_live_log(log_path, _read_log_tail(log_path))
                    _update_rip_status(total_urls, total_urls, "Streamrip run finished.")
                    st.session_state.rip_last_log_path = log_path
                    if failures or skipped or successes:
                        if failures:
                            _ui_processing_debug(
                                f"Streamrip run completed with {len(failures)} failure(s)."
                            )
                        if skipped:
                            _ui_processing_debug(
                                f"Streamrip run completed with {len(skipped)} skipped URL(s)."
                            )
                        if successes:
                            _ui_processing_debug(
                                f"Streamrip run completed with {len(successes)} success(es)."
                            )
                        st.session_state.rip_last_level = "warning" if failures else "success"
                        st.session_state.rip_last_failures = failures
                        st.session_state.rip_last_skipped = skipped
                        st.session_state.rip_last_successes = successes
                        st.session_state.rip_last_message = (
                            f"Auto rip processed {total_urls} URL(s). See results below:"
                        )
                    else:
                        _ui_processing_debug("Streamrip run completed successfully.")
                        st.session_state.rip_last_level = "success"
                        st.session_state.rip_last_failures = []
                        st.session_state.rip_last_skipped = []
                        st.session_state.rip_last_message = (
                            f"Rip finished for {success_count} batch file(s) / {total_urls} URL(s)."
                        )
                st.rerun()
        except Exception as e:
            _ui_processing_debug(f"Error during export/rip action: {e}")
            st.session_state.auto_scroll_alerts_once = True
            st.error(f"Error during export/rip: {e}")

    if st.session_state.rip_last_message:
        if st.session_state.rip_last_level == "success":
            st.success(st.session_state.rip_last_message)
        elif st.session_state.rip_last_level == "error":
            st.session_state.auto_scroll_alerts_once = True
            st.error(st.session_state.rip_last_message)
        elif st.session_state.rip_last_level == "warning":
            st.session_state.auto_scroll_alerts_once = True
            st.warning(st.session_state.rip_last_message)
        else:
            st.info(st.session_state.rip_last_message)
            
        _failed_list = st.session_state.get("rip_last_failures", [])
        _skipped_list = st.session_state.get("rip_last_skipped", [])
        _success_list = st.session_state.get("rip_last_successes", [])
        if _failed_list or _skipped_list or _success_list:
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
    if st.session_state.rip_last_log_path and os.path.exists(st.session_state.rip_last_log_path):
        st.caption(f"Last rip log: {st.session_state.rip_last_log_path}")
        with open(st.session_state.rip_last_log_path, "r", encoding="utf-8", errors="replace") as f:
            log_text = f.read()
        st.download_button(
            "Download Last Rip Log",
            data=log_text,
            file_name="streamrip_last.log",
            mime="text/plain",
        )
        st.text_area("Last Rip Log (tail)", value=log_text[-4000:], height=220)

def run_tracker_diagnostic(artist: str, album: str, upc: Optional[str] = None) -> None:
    """
    Performs a one-off duplicate check for diagnostic purposes.
    """
    _ui_processing_debug(f"Running diagnostic check for: {artist} - {album} (UPC: {upc})")
    
    red_key = os.getenv("RED_API_KEY", "")
    ops_key = os.getenv("OPS_API_KEY", "")
    red_url = os.getenv("RED_URL", "https://redacted.sh").rstrip("/")
    ops_url = os.getenv("OPS_URL", "https://orpheus.network").rstrip("/")
    
    trackers = []
    if red_key:
        trackers.append(GazelleAPI("RED", red_url, api_key=red_key))
    if ops_key:
        trackers.append(GazelleAPI("OPS", ops_url, api_key=ops_key))
        
    if not trackers:
        st.error("No tracker API tokens found in .env. Configuration required.")
        return

    async def _do_diagnostic():
        results = []
        for tracker in trackers:
            with st.spinner(f"Querying {tracker.site_name}..."):
                is_dupe, message = await tracker.search_duplicates(artist, album, upc=upc)
                results.append((tracker.site_name, is_dupe, message))
        return results

    diag_results = asyncio.run(_do_diagnostic())
    
    st.markdown("### 🔍 Diagnostic Results")
    for site, is_dupe, msg in diag_results:
        if is_dupe:
            st.warning(f"**{site}:** 🚩 Dupe Detected! ({msg})")
        else:
            if "⚠️" in msg or "Error" in msg:
                st.error(f"**{site}:** {msg}")
            else:
                st.success(f"**{site}:** ✅ No duplicate found. {msg}")
