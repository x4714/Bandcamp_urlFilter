# Bandcamp to Qobuz Matcher

A Python Streamlit application to filter Bandcamp URLs and find exact high-resolution matches on Qobuz.

This tool helps you:
- Filter Bandcamp URLs based on various criteria (genre, location, track count, pricing).
- Scrape metadata from filtered Bandcamp releases.
- Search for matching albums on Qobuz.
- Export Qobuz links for matched albums.

## 🚀 Funktionen

- **Web-UI (Streamlit)**: User-friendly interface for easy interaction.
- **Bandcamp URL Filtering**: Filter input URLs by genre/tag, location, release date range, minimum/maximum track count, and pricing (free/paid/all).
- **Bandcamp Metadata Scraping**: Automatically fetches artist, album title, track count, etc., from Bandcamp pages.
- **Qobuz Matching**: Searches Qobuz for exact matches based on Bandcamp metadata.
- **Fuzzy Matching**: Uses `rapidfuzz` for robust artist and album title matching.
- **Export Qobuz Links**: Download a `.txt` file containing all matched Qobuz URLs.
- **Dry Run Mode**: Apply Bandcamp filters without performing Qobuz searches, useful for quick filtering.

## 🛠️ Installation

### Voraussetzungen
- Python 3.10 oder höher
- `pip` Paketmanager

### Schritte
1. Repository klonen oder herunterladen:
   ```bash
   git clone https://github.com/HauZ22/Bandcamp_urlFilter.git
   cd Bandcamp_urlFilter
   ```

2. Virtuelle Umgebung erstellen und aktivieren (empfohlen):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Unter Windows: .venv\Scripts\activate
   ```

3. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
   (Sie müssen möglicherweise eine `requirements.txt` Datei erstellen, die `streamlit`, `pandas`, `aiohttp`, `rapidfuzz`, `python-dotenv` enthält.)

## ⚙️ Konfiguration (Qobuz API)

Für die Metadaten-Suche bei Qobuz werden API-Zugangsdaten benötigt. Erstelle dazu im Hauptverzeichnis eine `.env` Datei. Diese Datei wird von Git ignoriert und enthält sensible Daten.

Beispiel für den Inhalt der `.env` Datei:
```env
# Optional: Setze deine eigene Qobuz App ID (Standard ist ein offener Web-Client 100000000)
QOBUZ_APP_ID=100000000
# Erforderlich (je nach Region/Account-Typ): Setze deinen User Auth Token für Qobuz
QOBUZ_USER_AUTH_TOKEN=dein_qobuz_token_hier
```

## 📖 Nutzung

1. Starten Sie die Streamlit-Anwendung:
   ```bash
   python -m streamlit run app.py
   ```
2. Die Anwendung öffnet sich automatisch in Ihrem Webbrowser.
3. Laden Sie eine `.txt` oder `.log`-Datei mit Bandcamp-URLs hoch.
4. Konfigurieren Sie die Filter in der Seitenleiste.
5. Klicken Sie auf "Process", um die URLs zu filtern und Qobuz-Matches zu finden.
