# Bandcamp LinkFilter

Ein Python-Tool zum Filtern und Extrahieren von Bandcamp-Links aus IRC-Logdateien. Dieses Programm hilft dabei, gezielt Musik-Releases zu finden, die bestimmten Kriterien entsprechen (z. B. Jahr 2026, kostenlos/free, Mindestanzahl an Tracks).
Diese Liste kann im Anschluss z.B. mit bcdl heruntergeladen werden.

## 🚀 Funktionen

- **GUI-Oberfläche**: Oberfläche mit Tkinter/CustomTkinter.
- **Zwei Betriebsmodi**:
  - **Import**: Verarbeitet eine bestehende Logdatei und exportiert die Ergebnisse.
  - **Monitor**: Überwacht eine Logdatei in Echtzeit auf neue Einträge.
- **Umfangreiche Filter**:
  - Filterung nach Bandcamp-URLs.
  - Automatische Filterung nach Releases aus **2026**.
  - Filterung nach **kostenlosen** ("free") Releases.
  - Einstellbare Mindest- und Maximalanzahl an **Tracks**.
  - Einstellbare Mindest- und Maximaldauer (**Minuten**).
- **Intelligenter Export**:
  - Vermeidung von Duplikaten.
  - Optionale Beschreibung an URLs anhängen (wird in einer neuen Zeile unter der URL ausgegeben, kompatibel mit `bcdl`).
  - Anpassbare Dateinamen mit optionalen Filter-Infos im Namen.
  - Filterung nach Zeitstempel (nur neue Einträge seit dem letzten Export).
- **Statistiken & Dry-Run**: "Search / Dry Run" Funktion, um Treffer zu zählen, ohne eine Datei zu schreiben.

## 🛠️ Installation

### Voraussetzungen
- Python 3.10 oder höher

### Schritte
1. Repository klonen oder herunterladen:
   ```bash
   git clone https://github.com/HauZ22/Bandcamp_urlFilter.git
   cd Bandcamp_urlFilter
   ```

2. Virtuelle Umgebung erstellen (empfohlen):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Unter Windows: .venv\Scripts\activate
   ```

3. Abhängigkeiten installieren:
   Das Projekt verwendet Standard-Python-Bibliotheken und `tkinter`. Falls zusätzliche Pakete benötigt werden, können diese via `pip` installiert werden.

## 📖 Nutzung

1. Starten Sie das Programm über die `run.bat` (Windows) oder direkt via Python:
   ```bash
   python main.py
   ```
2. **Log-Datei auswählen**: Wählen Sie die IRC-Logdatei aus, die gescannt werden soll.
3. **Ausgabeordner wählen**: Legen Sie fest, wo die gefilterten Links gespeichert werden sollen.
4. **Filter einstellen**: Geben Sie bei Bedarf Min/Max Tracks oder Dauer ein.
5. **Starten**: Klicken Sie auf "Start", um den Prozess zu beginnen.
