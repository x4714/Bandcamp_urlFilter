@echo off
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

echo Checking required environment variables...
python -c "import os, sys, pathlib; p=pathlib.Path('.env'); text=p.read_text() if p.exists() else ''; [os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39))) for line in text.splitlines() if line.strip() and not line.strip().startswith('#') and '=' in line for k, v in [line.split('=',1)]]; required=['QOBUZ_USER_AUTH_TOKEN']; missing=[k for k in required if not os.environ.get(k)];
if missing:
    print('Missing required environment variables: ' + ', '.join(missing));
    print();
    print('Create a .env file in the project root with:');
    print('PYTHONPATH=.');
    print('QOBUZ_APP_ID=100000000');
    print('QOBUZ_USER_AUTH_TOKEN=your_qobuz_token_here');
    sys.exit(1)
"
if %ERRORLEVEL% NEQ 0 (
    goto error
)

python -m streamlit run app.py
pause