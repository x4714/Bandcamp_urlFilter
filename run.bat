@echo off
setlocal
echo Starting Bandcamp to Qobuz Matcher Web UI...
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
set "STREAMLIT_SERVER_HEADLESS=true"

set "PY_CMD="
where py >nul 2>nul && (
    py -3.13 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.13"
    if not defined PY_CMD py -3.12 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.12"
    if not defined PY_CMD py -3.11 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.11"
    if not defined PY_CMD py -3.10 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.10"
    if not defined PY_CMD py -3.9 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.9"
)
if not defined PY_CMD (
    where python >nul 2>nul && (
        python -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 and sys.version_info.minor >= 9 and sys.version_info.minor <= 13 else 1)" >nul 2>nul && set "PY_CMD=python"
    )
)
if not defined PY_CMD (
    echo Error: Python 3.9-3.13 is required but no compatible interpreter was found on PATH.
    goto error
)

if not exist .venv\Scripts\python.exe (
    goto create_venv
)

if not exist .venv\Scripts\activate.bat (
    echo Existing .venv looks incomplete. Recreating it...
    rmdir /s /q .venv
    goto create_venv
)

.venv\Scripts\python.exe -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 and sys.version_info.minor >= 9 and sys.version_info.minor <= 13 else 1)" >nul 2>nul
if errorlevel 1 (
    echo Existing .venv is not using Python 3.9-3.13. Recreating it...
    rmdir /s /q .venv
    goto create_venv
)

goto install_deps

:create_venv
echo Creating virtual environment...
%PY_CMD% -m venv .venv || goto error

:install_deps
echo Checking dependencies (quiet mode)...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q --upgrade pip || goto error
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt || goto error

echo Checking Qobuz environment variables (optional for Dry Run)...
if not exist .env (
    echo Warning: .env not found. Dry Run mode will still work.
) else (
    findstr /R /C:"^[ ]*QOBUZ_USER_AUTH_TOKEN[ ]*=" .env >nul
    if errorlevel 1 (
        echo Warning: QOBUZ_USER_AUTH_TOKEN is missing from .env. Dry Run mode will still work.
    )
)

.venv\Scripts\python.exe -m streamlit run app.py --server.headless=true || goto error
pause
exit /b 0

:error
echo.
echo Notes:
echo - This launcher expects Python 3.9-3.13.
echo - If only Python 3.14 is installed, install Python 3.13 or use Docker.
echo Launcher failed. Review messages above and fix the issue, then try again.
pause
exit /b 1
