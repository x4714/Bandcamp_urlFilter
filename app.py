import streamlit as st
import pandas as pd
import asyncio
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

# Sidebar Configuration
st.sidebar.header("Filter Configuration")

tag_input = st.sidebar.text_input("🏷️ Genre / Tag", value="", help="Filter by Tag or Genre")
location_input = st.sidebar.text_input("📍 Location", value="", help="Filter by Location parsing")
min_tracks = st.sidebar.number_input("🔢 Min Tracks", min_value=1, value=None, step=1, help="Leave empty for no minimum")
max_tracks = st.sidebar.number_input("🔢 Max Tracks", min_value=1, value=None, step=1, help="Leave empty for no maximum")
min_duration = st.sidebar.number_input("⏱️ Min Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no minimum")
max_duration = st.sidebar.number_input("⏱️ Max Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no maximum")

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Release Date")
start_date = st.sidebar.date_input("Start Date", value=None, help="Filter for releases on or after this date.")
end_date = st.sidebar.date_input("End Date", value=None, help="Filter for releases on or before this date.")
st.sidebar.markdown("---")

free_mode = st.sidebar.selectbox("💸 Pricing", options=["All", "Free", "Paid"], index=0)

dry_run = st.sidebar.checkbox("🏜️ Dry Run", value=False, help="Only apply Bandcamp filter, skip Qobuz search")

uploaded_file = st.file_uploader("Upload .txt file with Bandcamp URLs", type=['txt'])

def get_download_link(data_list: List[dict]) -> str:
    # Extracts the qobuz URLs to export file
    qobuz_urls = [d["qobuz_url"] for d in data_list if d.get("qobuz_url")]
    return "\n".join(qobuz_urls)

async def process_urls(lines: List[str]):
    filter_config = {
        "tag": tag_input,
        "location": location_input,
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
        return

    # 2. Process
    results = []
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
                    results.append({
                        "Artist": bc_data.get("artist"),
                        "Album": bc_data.get("album"),
                        "Bandcamp Link": bc_data.get("url"),
                        "Qobuz Link": match_data.get("qobuz_url"),
                        "Status": "✅ Matched"
                    })
                else:
                    results.append({
                        "Artist": bc_data.get("artist"),
                        "Album": bc_data.get("album"),
                        "Bandcamp Link": bc_data.get("url"),
                        "Qobuz Link": "",
                        "Status": "❌ No Match on Qobuz"
                    })
            else:
                results.append({
                    "Artist": entry.artist,
                    "Album": entry.title,
                    "Bandcamp Link": entry.url,
                    "Qobuz Link": "",
                    "Status": "⚠️ Error scraping Bandcamp"
                })
                
            progress_bar.progress((i + 1) / total)
            
    log_area.text(f"Complete! We found {len([r for r in results if r['Qobuz Link']])} out of {total} matches.")
    
    if results:
        df = pd.DataFrame(results)
        
        # UI DataFrame configuration
        st.dataframe(
            df,
            column_config={
                "Bandcamp Link": st.column_config.LinkColumn("Bandcamp URL"),
                "Qobuz Link": st.column_config.LinkColumn("Qobuz URL")
            },
            use_container_width=True
        )
        
        # Download button
        qobuz_strings = get_download_link([{"qobuz_url": r["Qobuz Link"]} for r in results])
        st.download_button(
            label="Download Qobuz Links (.txt)",
            data=qobuz_strings,
            file_name="qobuz_exports.txt",
            mime="text/plain"
        )
        

if st.button("Process", type="primary"):
    if uploaded_file is not None:
        # To convert to a list of strings
        stringio = StringIO(uploaded_file.getvalue().decode("utf-8"))
        lines = stringio.readlines()
        
        # Because Streamlit doesn't support async event loops natively in its top level without a workaround,
        # we can use asyncio.run to kick it off
        asyncio.run(process_urls(lines))
    else:
        st.error("Please upload a .txt file first.")
