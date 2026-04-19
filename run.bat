@echo off
setlocal
echo Starting Bandcamp to Qobuz Matcher Web UI...
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
set "STREAMLIT_SERVER_HEADLESS=true"

set "PY_CMD="
where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD (
    where py >nul 2>nul && set "PY_CMD=py -3"
)
if not defined PY_CMD (
    echo Error: Python 3.10+ is required but was not found on PATH.
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
echo - Python 3.14+ runs the core app, but the optional streamrip CLI is skipped because upstream does not yet support it there.
echo - Docker remains the most reliable full-featured path if you need in-app ripping.
echo Launcher failed. Review messages above and fix the issue, then try again.
pause
exit /b 1
