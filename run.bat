@echo off
setlocal
echo Starting Bandcamp to Qobuz Matcher Web UI...
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv || goto error
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
    echo Installing dependencies...
    python -m pip install --upgrade pip || goto error
    python -m pip install -r requirements.txt || goto error
) else (
    call .venv\Scripts\activate.bat
)

echo Checking Qobuz environment variables (optional for Dry Run)...
if not exist .env (
    echo Warning: .env not found. Dry Run mode will still work.
) else (
    findstr /R /C:"^[ ]*QOBUZ_USER_AUTH_TOKEN[ ]*=" .env >nul
    if errorlevel 1 (
        echo Warning: QOBUZ_USER_AUTH_TOKEN is missing from .env. Dry Run mode will still work.
    )
)

python -m streamlit run app.py || goto error
pause
exit /b 0

:error
echo.
echo Launcher failed. Review messages above and fix the issue, then try again.
pause
exit /b 1
