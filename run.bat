@echo off
echo Starting Bandcamp to Qobuz Matcher Web UI...
call .venv\Scripts\activate.bat
python -m streamlit run app.py
pause