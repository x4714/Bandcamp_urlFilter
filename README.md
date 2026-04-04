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
- **Bandcamp Metadata Scraping**: Automatically fetches artist, album title, track count, etc., from Bandcamp pages.
- **Qobuz Matching**: Searches Qobuz for exact matches based on Bandcamp metadata.
- **Fuzzy Matching**: Uses `rapidfuzz` for robust artist and album title matching.
- **Export Qobuz Links**: Download a `.txt` file containing all matched Qobuz URLs.
- **Dry Run Mode**: Apply Bandcamp filters without performing Qobuz searches, useful for quick filtering.

## 🛠️ Installation

### Prerequisites
- Python 3.10 or higher
- `pip` package manager

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
# Optional: Set your own Qobuz App ID (default is an open web client 100000000)
QOBUZ_APP_ID=100000000
# Required (depending on region/account type): Set your user Auth Token for Qobuz
QOBUZ_USER_AUTH_TOKEN=your_qobuz_token_here
```

## 📖 Usage

1. Start the Streamlit application:
   ```bash
   python -m streamlit run app.py
   ```
2. The application opens automatically in your web browser.
3. Upload a `.txt` or `.log` file containing Bandcamp URLs.
4. Configure the filters in the sidebar.
5. Click "Process" to filter the URLs and find Qobuz matches.
