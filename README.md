# Bandcamp to Qobuz Matcher

[![Docker Image](https://github.com/HauZ22/Bandcamp_urlFilter/actions/workflows/docker-image.yml/badge.svg)](https://github.com/HauZ22/Bandcamp_urlFilter/actions/workflows/docker-image.yml)
[![GHCR](https://img.shields.io/badge/GHCR-bandcamp--urlfilter-2496ED?logo=docker&logoColor=white)](https://github.com/HauZ22/Bandcamp_urlFilter/pkgs/container/bandcamp-urlfilter)

A Streamlit application for filtering Bandcamp release URLs, scraping release metadata, matching against Qobuz, and exporting links for downstream ripping or upload workflows.

## Overview

This tool helps you:

- filter Bandcamp URLs by genre, location, release date, track count, and price
- parse both plain URL lists and enriched log-style input
- scrape Bandcamp release metadata automatically
- find exact or fuzzy Qobuz matches
- export matched Qobuz URLs
- run Streamrip directly from the UI
- prepare downloaded releases for `smoked-salmon`

## Features

- `Streamlit` web UI
- Bandcamp URL filtering and metadata scraping
- Qobuz matching with `rapidfuzz`
- optional 24-bit / hi-res filter (skip albums not available in lossless hi-res on Qobuz)
- configurable concurrency, request delay, and per-service retry/back-off via the UI
- optional per-service proxy routing (`GLOBAL_PROXY`, `BANDCAMP_PROXY`, `QOBUZ_PROXY`, `TRACKER_PROXY`)
- Dry Run mode for filtering without Qobuz requests
- export helpers for `streamrip`
- direct Streamrip tab inside the app
- Smoked Salmon setup, config editing, and upload helpers
- launchers for Windows, macOS, and Linux shells
- HostingByDesign-style user-service installer
- Docker and Docker Compose support

## Quick Start

Docker Compose is the preferred way to run this project.

If you already have a Compose stack, add this service:

```yaml
services:
  bandcamp-urlfilter:
    image: ghcr.io/hauz22/bandcamp-urlfilter:latest
    container_name: bandcamp-urlfilter
    ports:
      - "8501:8501"
    environment:
      QOBUZ_USER_AUTH_TOKEN: ${QOBUZ_USER_AUTH_TOKEN}
      QOBUZ_APP_ID: ${QOBUZ_APP_ID:-}
      APP_AUTH_ENABLED: ${APP_AUTH_ENABLED:-0}
      APP_AUTH_USERNAME: ${APP_AUTH_USERNAME:-}
      APP_AUTH_PASSWORD_HASH: ${APP_AUTH_PASSWORD_HASH:-}
      APP_AUTH_SESSION_TTL_SECONDS: ${APP_AUTH_SESSION_TTL_SECONDS:-43200}
      APP_AUTH_MAX_FAILURES: ${APP_AUTH_MAX_FAILURES:-5}
      APP_AUTH_LOCKOUT_SECONDS: ${APP_AUTH_LOCKOUT_SECONDS:-900}
      APP_AUTH_COOKIE_NAME: ${APP_AUTH_COOKIE_NAME:-bandcamp_urlfilter_auth_session}
      APP_AUTH_COOKIE_SECURE: ${APP_AUTH_COOKIE_SECURE:-1}
      APP_DEBUG_LOG_ENABLED: ${APP_DEBUG_LOG_ENABLED:-0}
      APP_DEBUG_STDERR: ${APP_DEBUG_STDERR:-0}
      APP_TIMEZONE: ${APP_TIMEZONE:-UTC}
      RED_API_KEY: ${RED_API_KEY:-}
      RED_SESSION_COOKIE: ${RED_SESSION_COOKIE:-}
      RED_URL: ${RED_URL:-https://redacted.sh}
      OPS_API_KEY: ${OPS_API_KEY:-}
      OPS_SESSION_COOKIE: ${OPS_SESSION_COOKIE:-}
      OPS_URL: ${OPS_URL:-https://orpheus.network}
      GLOBAL_PROXY: ${GLOBAL_PROXY:-}
      BANDCAMP_PROXY: ${BANDCAMP_PROXY:-}
      QOBUZ_PROXY: ${QOBUZ_PROXY:-}
      TRACKER_PROXY: ${TRACKER_PROXY:-}
    volumes:
      - ./exports:/app/exports
      - ./docker-data/config:/config
      - ./docker-data/downloads:/downloads
    restart: unless-stopped
```

Then create `.env` from [`.env.example`](.env.example), add your Qobuz token, and start it:

```bash
cp .env.example .env
docker compose up -d
```

Open `http://localhost:8501`.

Persistent paths:

- `./exports`
- `./docker-data/config`
- `./docker-data/downloads`

If you want to use the repo's ready-made GHCR compose file instead of pasting a service into your own stack:

```bash
cp .env.example .env
docker compose -f docker-compose.ghcr.yml up -d
```

More Docker details live in [docs/docker.md](docs/docker.md).

## Configuration

Create `.env` from [`.env.example`](.env.example):

```bash
cp .env.example .env
```

Example:

```env
PYTHONPATH=.
# QOBUZ_APP_ID=
QOBUZ_USER_AUTH_TOKEN=your_qobuz_token_here
# Optional public app auth:
APP_AUTH_ENABLED=0
APP_AUTH_USERNAME=
APP_AUTH_PASSWORD_HASH=
APP_AUTH_SESSION_TTL_SECONDS=43200
APP_AUTH_MAX_FAILURES=5
APP_AUTH_LOCKOUT_SECONDS=900
APP_AUTH_COOKIE_NAME=bandcamp_urlfilter_auth_session
APP_AUTH_COOKIE_SECURE=1
# Optional debug logging (disabled by default):
APP_DEBUG_LOG_ENABLED=0
APP_DEBUG_STDERR=0
# Optional tracker/upload helpers:
RED_API_KEY=
RED_SESSION_COOKIE=
# RED_URL=https://redacted.sh
OPS_API_KEY=
OPS_SESSION_COOKIE=
# OPS_URL=https://orpheus.network
# Optional proxy settings (all default off):
# GLOBAL_PROXY=http://user:pass@host:port
# BANDCAMP_PROXY=http://user:pass@host:port
# QOBUZ_PROXY=http://user:pass@host:port
# TRACKER_PROXY=http://user:pass@host:port
```

Notes:

- `QOBUZ_USER_AUTH_TOKEN` is required for live Qobuz matching.
- `QOBUZ_APP_ID` is optional. If it is missing, the app tries to discover it from the Qobuz web player.
- `APP_AUTH_*` is optional, but strongly recommended if the app will be reachable on the public web. `APP_AUTH_COOKIE_NAME` lets you namespace the browser cookie when several apps share the same host.
- Important auth limitation: because Streamlit does not expose a server-side `Set-Cookie` hook here, the built-in app auth cookie is synchronized from client-side JavaScript and therefore cannot be `HttpOnly`. Use HTTPS, keep `APP_AUTH_COOKIE_SECURE=1`, and prefer reverse-proxy or IdP-backed auth in front of the app for Internet-facing deployments.
- Built-in app auth now expires authenticated sessions after 12 hours by default and locks sign-in after 5 failed attempts for 15 minutes.
- `APP_TIMEZONE` is optional and controls user-facing timestamp display in the UI. It accepts IANA timezone names such as `UTC`, `Europe/Berlin`, or `America/New_York`. If omitted or invalid, the app falls back to `UTC`.
- tracker credentials are optional and only needed for duplicate checking / upload helper features
- proxy vars are all optional and off by default. `GLOBAL_PROXY` is the fallback for every service; service-specific vars (`BANDCAMP_PROXY`, `QOBUZ_PROXY`, `TRACKER_PROXY`) override it for that service only. Supported schemes: `http://`, `https://`, `socks5://`.
- `.env` is ignored by Git.

## Requirements

- Python 3.9 to 3.13 for local launcher workflows
- `pip`
- Git available on `PATH` if you install from `requirements.txt` because `streamrip` is pulled from GitHub

Python compatibility notes:

- the launchers target Python 3.9-3.13
- the optional bundled `streamrip` CLI currently installs automatically on Python 3.10-3.13
- if only Python 3.14 is installed, `run.sh` and `setup-hbd.sh` now auto-bootstrap a userland `pyenv` Python (default `3.11.11`) unless you disable that fallback
- if `pyenv` cannot build Python on your host, use Docker or point `PYTHON_BIN` at an existing Python 3.9-3.13 binary

Optional but useful for ripping/upload workflows:

- `flac`
- `sox`
- `lame`
- `mp3val`
- `curl`
- `git`
- `uv` for installing `smoked-salmon`

## Other Ways To Run

If you do not want the default GHCR-based Docker Compose setup, these are the other supported paths.

### Docker From This Checkout

Build from this repository instead of using the published image:

```bash
cp .env.example .env
docker compose up --build -d
```

The repo also includes:

- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)
- [docker-compose.ghcr.yml](docker-compose.ghcr.yml)
- [docker/entrypoint.sh](docker/entrypoint.sh)

The compose services now pass through every app env var from [`.env.example`](.env.example), so you can override them from your shell environment, the project `.env` file, or `docker compose --env-file ...`.

Automated image publishing:

- pull requests build the Docker image for validation
- pushes to `main` or `master` publish `ghcr.io/hauz22/bandcamp-urlfilter:latest`
- Git tags like `v1.2.3` publish matching version tags

### Local Usage

#### Fastest path

- Linux: `./run.sh`
- macOS: `./run.command`
- Windows: `run.bat`

Each launcher creates `.venv` if needed, installs dependencies, warns when Qobuz auth is missing, and starts Streamlit.

Launcher notes:

- `run.sh`/`run.command` now prefer Python `3.13 -> 3.9`, then bootstrap `pyenv` if needed
- `run.bat` now prefers installed `py -3.13 .. -3.9` runtimes (or `python` if already in range)
- if an earlier failed bootstrap left behind a partial `.venv`, the launchers recreate it
- `run.sh`/`setup-hbd.sh` avoid Python 3.14+ automatically and pick/build a compatible runtime

#### Manual path

```bash
git clone https://github.com/HauZ22/Bandcamp_urlFilter.git
cd Bandcamp_urlFilter
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit run app.py
```

On Windows, activate with:

```powershell
.venv\Scripts\activate
```

#### macOS first run

If Finder blocks `run.command`:

```bash
chmod +x run.command
xattr -d com.apple.quarantine run.command
```

### HostingByDesign / App Box Setup

[`setup-hbd.sh`](setup-hbd.sh) is the new Linux helper for boxes where you want a user-managed service instead of manually starting Streamlit every session.

Quick start:

```bash
chmod +x setup-hbd.sh
./setup-hbd.sh
```

HostingByDesign note:

- `setup-hbd.sh` looks for Python `3.13 -> 3.9` first
- if it only finds Python 3.14+ or nothing suitable on `PATH`, it bootstraps `pyenv` in `~/.local/opt/pyenv` and builds a userland Python automatically
- if your box has a newer interpreter at a specific name, run for example `PYTHON_BIN=python3.11 ./setup-hbd.sh`
- if you do not want that fallback, run `./setup-hbd.sh --skip-pyenv-bootstrap`
- `smoked-salmon` should still be installed separately with `uv`, which manages its own Python/runtime isolation

What it does:

- creates a reusable virtualenv in `~/.config/venv/bandcamp-urlfilter`
- installs dependencies
- requires and configures built-in app auth for the current shell user when the app is being exposed on a public HBD domain
- creates `.env` from `.env.example` if needed
- chooses an available port
- writes a user `systemd` service
- enables and starts the service

Useful options:

```bash
./setup-hbd.sh --port 8765
./setup-hbd.sh --bind 0.0.0.0
./setup-hbd.sh --enable-auth
./setup-hbd.sh --disable-auth   # only valid with localhost-style binds
./setup-hbd.sh --no-start
```

More details live in [docs/hostingbydesign.md](docs/hostingbydesign.md).

If you expose the app directly or through a public reverse proxy on HBD, built-in app auth is required and you should terminate HTTPS at the proxy. The built-in gate is intended as a lightweight single-user login, not a substitute for TLS or a full identity provider.

## In-App Workflow

1. open the app in your browser
2. upload a `.txt` or `.log` file containing Bandcamp URLs
3. set your filters — pricing, date range, genre, track count, etc.
4. optionally toggle **Only 24-bit** to restrict Qobuz results to hi-res albums
5. optionally expand **Rate Limits & Retries** in the sidebar to tune concurrency, request delay, and per-service retry back-off
6. click `Process`
7. export matched Qobuz URLs if needed
8. optionally run Streamrip or Smoked Salmon from their UI tabs

If you need to stop a run, use `Stop / Cancel` to finish the current in-flight batch and keep partial results.

## Exports and Ripping

- export files are written to `exports/`
- the app generates `run_rip.sh` and `run_rip.bat` in the repo root; those helper scripts read the batch files from `exports/`
- `streamrip` is included in `requirements.txt`
- bundled `streamrip` install is enabled on Python 3.10-3.13
- `smoked-salmon` can be installed with:

```bash
uv tool install git+https://github.com/smokin-salmon/smoked-salmon
```

## Script Reference

See [docs/scripts.md](docs/scripts.md) for a summary of every launcher and helper script in the repo.
