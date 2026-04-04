import streamlit as st
import pandas as pd
import os
import asyncio
import subprocess
import shutil
import sys
from datetime import date
import aiohttp
from io import StringIO
from typing import List

from logic.bandcamp_filter import filter_entries
from logic.metadata_scraper import scrape_bandcamp_metadata
from logic.qobuz_matcher import match_album

st.set_page_config(page_title="Bandcamp to Qobuz Matcher", layout="wide")

st.title("🎵 Bandcamp to Qobuz Matcher")
st.markdown("Filter your Bandcamp URLs and find exact high-resolution matches on Qobuz.")

if "results" not in st.session_state:
    st.session_state.results = []
if "process_complete" not in st.session_state:
    st.session_state.process_complete = False
if "export_done" not in st.session_state:
    st.session_state.export_done = False

def open_in_default_app(path: str) -> None:
    target = os.path.abspath(path)
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
        return

    opener = shutil.which("xdg-open")
    if not opener:
        raise RuntimeError("Could not find xdg-open to launch files/folders.")
    subprocess.Popen([opener, target])

# Sidebar Configuration
st.sidebar.header("Filter Configuration")

tag_input = st.sidebar.text_input("🏷️ Genre / Tag", value="", help="Filter by Tag or Genre")
min_tracks = st.sidebar.number_input("🔢 Min Tracks", min_value=1, value=None, step=1, help="Leave empty for no minimum")
max_tracks = st.sidebar.number_input("🔢 Max Tracks", min_value=1, value=None, step=1, help="Leave empty for no maximum")
min_duration = st.sidebar.number_input("⏱️ Min Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no minimum")
max_duration = st.sidebar.number_input("⏱️ Max Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no maximum")

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Settings")
if st.sidebar.button("📝 Open .env File for Qobuz Token -> see README.md"):
    env_path = ".env"
    if not os.path.exists(env_path):
        template = """# Important: So that Python recognizes local directories (e.g., logic) as modules
PYTHONPATH=.
# Optional: Set your own Qobuz App ID (default is an open web client 100000000)
QOBUZ_APP_ID=100000000
# Required (depending on region/account type): Set your user Auth Token for Qobuz
QOBUZ_USER_AUTH_TOKEN="""
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(template)
        except Exception as e:
            st.sidebar.error(f"Error creating the .env file: {e}")

    try:
        open_in_default_app(env_path)
    except Exception as e:
        st.sidebar.error(f"Could not open .env: {e}")

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Release Date")
start_date = st.sidebar.date_input("Start Date", value=None, help="Filter for releases on or after this date.")
end_date = st.sidebar.date_input("End Date", value=None, help="Filter for releases on or before this date.")
st.sidebar.markdown("---")

free_mode = st.sidebar.selectbox("💸 Pricing", options=["All", "Free", "Paid"], index=0)

dry_run = st.sidebar.checkbox("🏜️ Dry Run", value=False, help="Only apply Bandcamp filter, skip Qobuz search")

uploaded_file = st.file_uploader("Upload .txt or .log file with Bandcamp URLs", type=['txt', 'log'])

def get_download_link(data_list: List[dict]) -> str:
    # Extracts the qobuz URLs to export file
    qobuz_urls = [d["qobuz_url"] for d in data_list if d.get("qobuz_url")]
    return "\n".join(qobuz_urls)

async def process_urls(lines: List[str]):
    filter_config = {
        "tag": tag_input,
        "min_tracks": int(min_tracks) if min_tracks else None,
        "max_tracks": int(max_tracks) if max_tracks else None,
        "min_duration": int(min_duration) if min_duration else None,
        "max_duration": int(max_duration) if max_duration else None,
        "free_mode": free_mode
    }
    
    st.write("### Status Log")
    log_area = st.empty()
    progress_bar = st.progress(0)
    
    # 1. Filter
    log_area.text("Applying filters...")
    filtered_entries = filter_entries(lines, filter_config)
    
    # Post-filter for date range
    if start_date or end_date:
        date_filtered_entries = []
        for entry in filtered_entries:
            if not entry.release_date:
                continue
            
            start_ok = not start_date or entry.release_date >= start_date
            end_ok = not end_date or entry.release_date <= end_date

            if start_ok and end_ok:
                date_filtered_entries.append(entry)
        
        filtered_entries = date_filtered_entries

    log_area.text(f"Found {len(filtered_entries)} URLs matching your filters out of {len(lines)} total lines.")

    if not filtered_entries:
        st.warning("No URLs matched the filter criteria.")
        return
        
    if dry_run:
        st.info("Dry Run enabled. Qobuz matching skipped. Showing filtered URLs:")
        df = pd.DataFrame([{ "Bandcamp URL": e.url, "Artist": e.artist, "Title": e.title, "Genre": e.genre, "Tracks": e.track_count, "Duration (min)": e.duration_min } for e in filtered_entries])
        st.dataframe(
            df,
            column_config={
                "Bandcamp URL": st.column_config.LinkColumn()
            },
            use_container_width=True
        )
        
        # Download button for filtered Bandcamp URLs
        bc_urls = "\n".join([e.url for e in filtered_entries if e.url])
        st.download_button(
            label="Download Filtered Bandcamp Links (.txt)",
            data=bc_urls,
            file_name="filtered_bandcamp_urls.txt",
            mime="text/plain"
        )
        return

    # Reset session state for a new run
    st.session_state.results = []
    st.session_state.process_complete = False
    st.session_state.export_done = False

    # 2. Process
    total = len(filtered_entries)
    
    # Run async sessions
    async with aiohttp.ClientSession() as session:
        for i, entry in enumerate(filtered_entries):
            log_area.text(f"[{i+1}/{total}] Fetching Bandcamp Metadata for {entry.url}...")
            bc_data = await scrape_bandcamp_metadata(entry.url, session)
            
            if bc_data.get("status") == "success":
                log_area.text(f"[{i+1}/{total}] Searching Qobuz for {bc_data.get('artist')} - {bc_data.get('album')}...")
                match_data = await match_album(session, bc_data)
                
                if match_data.get("status") == "matched":
                    st.session_state.results.append({
                        "Artist": bc_data.get("artist"),
                        "Album": bc_data.get("album"),
                        "Bandcamp Link": bc_data.get("url"),
                        "Qobuz Link": match_data.get("qobuz_url"),
                        "Status": "✅ Matched"
                    })
                else:
                    st.session_state.results.append({
                        "Artist": bc_data.get("artist"),
                        "Album": bc_data.get("album"),
                        "Bandcamp Link": bc_data.get("url"),
                        "Qobuz Link": "",
                        "Status": "❌ No Match on Qobuz"
                    })
            else:
                st.session_state.results.append({
                    "Artist": entry.artist,
                    "Album": entry.title,
                    "Bandcamp Link": entry.url,
                    "Qobuz Link": "",
                    "Status": "⚠️ Error scraping Bandcamp"
                })
                
            progress_bar.progress((i + 1) / total)
            
    st.session_state.process_complete = True
    log_area.text(f"Complete! We found {len([r for r in st.session_state.results if r['Qobuz Link']])} out of {total} matches.")
        

col1, col2 = st.columns([1, 5])
with col1:
    process_btn = st.button("Process", type="primary")
with col2:
    st.button("Stop / Cancel", help="Cancels the current search and displays the results so far.")

if process_btn:
    if uploaded_file is not None:
        # To convert to a list of strings
        stringio = StringIO(uploaded_file.getvalue().decode("utf-8"))
        lines = stringio.readlines()
        
        # Because Streamlit doesn't support async event loops natively in its top level without a workaround,
        # we can use asyncio.run to kick it off
        asyncio.run(process_urls(lines))
    else:
        st.error("Please upload a .txt or .log file first.")

# Show results outside the process function so they persist after cancellation
if not dry_run and st.session_state.results:
    st.markdown("---")
    st.subheader("📊 Results")
    
    if not st.session_state.process_complete:
        st.warning("⚠️ Processing was cancelled or interrupted. Showing partial results.")
    else:
        st.success("✅ Processing complete.")
    
    df = pd.DataFrame(st.session_state.results)
    
    st.dataframe(
        df,
        column_config={
            "Bandcamp Link": st.column_config.LinkColumn("Bandcamp URL"),
            "Qobuz Link": st.column_config.LinkColumn("Qobuz URL")
        },
        use_container_width=True
    )
    
    qobuz_strings = get_download_link([{"qobuz_url": r["Qobuz Link"]} for r in st.session_state.results])
    st.download_button(
        label="Download Qobuz Links (.txt)",
        data=qobuz_strings,
        file_name="qobuz_exports.txt",
        mime="text/plain"
    )

    st.markdown("---")
    st.subheader("💾 Local Export & Batch Generator")
    st.markdown("Split Qobuz links into multiple text files and generate a batch downloader script.")
    
    col_exp1, col_exp2 = st.columns([1, 2])
    with col_exp1:
        max_links = st.number_input("Max links per file", min_value=1, value=10, step=1)
        export_btn = st.button("Export to Local Disk", type="primary")
        
    with col_exp2:
        if export_btn:
            try:
                valid_urls = [r["Qobuz Link"] for r in st.session_state.results if r["Qobuz Link"]]
                if not valid_urls:
                    st.warning("No valid Qobuz links to export.")
                else:
                    export_dir = os.path.abspath("exports")
                    os.makedirs(export_dir, exist_ok=True)
                    
                    batch_files = []
                    total_batches = (len(valid_urls) + max_links - 1) // max_links
                    
                    for i in range(total_batches):
                        batch_urls = valid_urls[i * max_links : (i + 1) * max_links]
                        batch_num = f"{i + 1:02d}"
                        filename = f"qobuz_batch_{batch_num}.txt"
                        filepath = os.path.join(export_dir, filename)
                        
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write("\n".join(batch_urls) + "\n")
                            
                        batch_files.append(filename)
                        
                    bat_path = os.path.abspath("run_rip.bat")
                    with open(bat_path, "w", encoding="utf-8") as f:
                        f.write("@echo off\n")
                        for fname in batch_files:
                            f.write(f"call rip file exports/{fname}\n")
                        f.write("pause\n")

                    sh_path = os.path.abspath("run_rip.sh")
                    with open(sh_path, "w", encoding="utf-8") as f:
                        f.write("#!/usr/bin/env bash\n")
                        f.write("set -e\n\n")
                        for fname in batch_files:
                            f.write(f"rip file \"exports/{fname}\"\n")
                        f.write("printf '\nPress Enter to exit...'; read -r _\n")

                    try:
                        os.chmod(sh_path, 0o755)
                    except Exception:
                        pass

                    st.success(
                        f"Successfully created {total_batches} batch file(s) in `/exports/` and generated `run_rip.bat` and `run_rip.sh`.")
                    st.session_state.export_done = True
            except Exception as e:
                st.error(f"Error during export: {e}")
                
    if st.session_state.export_done:
        if st.button("📂 Open Exports Folder"):
            try:
                open_in_default_app("exports")
            except Exception as e:
                st.error(f"Could not open folder: {e}")
