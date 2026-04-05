# Bandcamp to Qobuz Matcher

A Python Streamlit application to filter Bandcamp URLs and find exact high-resolution matches on Qobuz.

This tool helps you:
- Filter Bandcamp URLs based on various criteria (genre, location, track count, pricing).
- Scrape metadata from filtered Bandcamp releases.
- Search for matching albums on Qobuz.
- Export Qobuz links for matched albums.

## 🚀 Features

- **Web-UI (Streamlit)**: User-friendly interface for easy interaction.
- **Bandcamp URL Filtering**: Filter input URLs by genre/tag, location, release date range, minimum/maximum track count, and pricing (free/paid/all).
- **Flexible Input Parsing**: Accepts both raw Bandcamp URL lists and enriched IRC/log-style lines.
- **Bandcamp Metadata Scraping**: Automatically fetches artist, album title, track count, etc., from Bandcamp pages.
- **Qobuz Matching**: Searches Qobuz for exact matches based on Bandcamp metadata.
- **Fuzzy Matching**: Uses `rapidfuzz` for robust artist and album title matching.
- **Export Qobuz Links**: Download a `.txt` file containing all matched Qobuz URLs.
- **Direct Qobuz Rip Tab**: Paste or upload Qobuz links and rip them immediately with streamrip.
- **Smoked Salmon Upload Tab**: Run `smoked-salmon` uploads for your downloaded release folders from inside the UI.
- **Smoked Salmon Config Editor**: Edit and save smoked-salmon `config.toml` and run `health/checkconf/migrate` directly from the UI.
- **Smoked Salmon Setup Assistant**: Checks required tools (`flac`, `sox`, `lame`, `mp3val`, `curl`, `git`) and auto-installs smoked-salmon with `uv` if missing.
- **Dry Run Mode**: Apply Bandcamp filters without performing Qobuz searches, useful for quick filtering.
- **Cross-platform Open Actions**: The `.env` helper button and exports folder button work on Windows, macOS, and Linux.
## 🛠️ Installation

### Prerequisites
- Python 3.10 or higher
- `pip` package manager
- Linux and macOS support
- Works in Bash and Fish shells

### Steps
1. Clone or download the repository:
   ```bash
   git clone https://github.com/HauZ22/Bandcamp_urlFilter.git
   cd Bandcamp_urlFilter
   ```

2. Create and activate a virtual environment (recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   (You may need to create a `requirements.txt` file containing `streamlit`, `pandas`, `aiohttp`, `rapidfuzz`, `python-dotenv`, `beautifulsoup4`.)

## ⚙️ Configuration (Qobuz API)

API credentials are required for Qobuz metadata search. Create a `.env` file in the main directory. This file is ignored by Git and contains sensitive data.

Example of the `.env` file content:
```env
# Important: So that Python recognizes local directories (e.g., logic) as modules
PYTHONPATH=.
# Optional: Set your own Qobuz App ID. If omitted, the app auto-fetches it from Qobuz Web Player.
# QOBUZ_APP_ID=
# Required (depending on region/account type): Set your user Auth Token for Qobuz
QOBUZ_USER_AUTH_TOKEN=your_qobuz_token_here
```

## 📖 Usage

1. Start the Streamlit application directly:
   ```bash
   python -m streamlit run app.py
   ```

2. Or use the provided launch scripts. Each script will create a virtual environment if needed, install dependencies, and validate Qobuz settings:
   - Bash: `./run.sh`
   - Fish: `./run.fish`
   - macOS (Finder-friendly): `./run.command`
   - Windows: `run.bat`

### macOS first run (Gatekeeper)
If macOS blocks `run.command` the first time, run:
```bash
chmod +x run.command
xattr -d com.apple.quarantine run.command
```
Then run `./run.command` again (or double-click it in Finder).

3. The application opens automatically in your web browser.
4. Upload a `.txt` or `.log` file containing Bandcamp URLs (raw URLs or enriched log lines).
5. Configure the filters in the sidebar.
6. Click "Process" to filter the URLs and find Qobuz matches.
7. Use "Stop / Cancel" to stop after the current in-flight batch and keep partial results.

## 🧾 Export

- After processing, use the export feature to write Qobuz links to `/exports/`.
- The app generates both `run_rip.bat` and `run_rip.sh` so Windows, Linux, and macOS users can run the downloader script.
- `streamrip` is included in `requirements.txt`; if not installed yet, run `pip install -r requirements.txt`.
- For tracker uploads, install `smoked-salmon`:
  ```bash
  uv tool install git+https://github.com/smokin-salmon/smoked-salmon
  ```
