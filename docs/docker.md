# Docker Setup

The container workflow is meant for people who want the app isolated from the host while still keeping config, downloads, and exports on disk.

## Recommended Setup

If you already run Docker Compose for other services, add this service to your existing stack:

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

Then:

```bash
cp .env.example .env
docker compose up -d
```

Open `http://localhost:8501`.

## Files Added

- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.ghcr.yml`
- `docker/entrypoint.sh`

## Automated Builds

GitHub Actions builds the image automatically:

- pull requests run a build-only validation job
- pushes to `main` or `master` publish `ghcr.io/hauz22/bandcamp-urlfilter:latest`
- version tags like `v1.2.3` publish versioned images

The workflow file lives at `.github/workflows/docker-image.yml`.

## Persistent Paths

The compose stack mounts:

- `./exports` -> `/app/exports`
- `./docker-data/config` -> `/config`
- `./docker-data/downloads` -> `/downloads`

Because `XDG_CONFIG_HOME=/config`, Streamrip config ends up at:

```text
/config/streamrip/config.toml
```

Inside the container, `$HOME/Music` is symlinked to `/downloads` so the default downloads target is usable immediately.

## Alternative Paths

### Local build from this repository

Create your environment file if needed:

```bash
cp .env.example .env
```

Build and start:

```bash
docker compose up --build -d
```

Open:

```text
http://localhost:8501
```

### Use the published GHCR image

Start the prebuilt image with the alternate compose file:

```bash
cp .env.example .env
docker compose -f docker-compose.ghcr.yml up -d
```

You can also pull it directly:

```bash
docker pull ghcr.io/hauz22/bandcamp-urlfilter:latest
```

If you want a different registry path or tag with `docker-compose.ghcr.yml`, override:

```bash
BANDCAMP_URLFILTER_IMAGE=ghcr.io/hauz22/bandcamp-urlfilter BANDCAMP_URLFILTER_TAG=v1.2.3 docker compose -f docker-compose.ghcr.yml up -d
```

## Environment Variables

The compose file accepts values from your shell environment or the project `.env` file and also sets:

```env
PYTHONPATH=/app
XDG_CONFIG_HOME=/config
STREAMLIT_SERVER_ADDRESS=0.0.0.0
STREAMLIT_SERVER_PORT=8501
```

Every app env var from [`.env.example`](../.env.example) is wired through the compose files, so you can override them from your shell, a compose `.env`, or `docker compose --env-file ...`.

Common examples:

- `QOBUZ_USER_AUTH_TOKEN` for live Qobuz matching
- `QOBUZ_APP_ID` if you want to pin it instead of relying on auto-discovery
- `APP_AUTH_*` to enable and tune the built-in login gate
- `APP_DEBUG_*` for debug logging
- `APP_TIMEZONE` for UI timestamp display
- `RED_*` / `OPS_*` for duplicate checking and upload helpers
- `GLOBAL_PROXY`, `BANDCAMP_PROXY`, `QOBUZ_PROXY`, and `TRACKER_PROXY` for per-service proxy routing

## Useful Commands

View logs:

```bash
docker compose logs -f
```

Restart after changing env vars:

```bash
docker compose up -d
```

Stop the stack:

```bash
docker compose down
```

Stop the GHCR-based stack:

```bash
docker compose -f docker-compose.ghcr.yml down
```

## Notes

- The image installs `git`, `curl`, `flac`, `sox`, `lame`, and `mp3val` so the UI's setup assistants have the expected base tools available.
- Exported URL batches are written to `/app/exports` and the generated `run_rip.sh` / `run_rip.bat` helper scripts are written to `/app`.
- Docker is still a good fallback when your host only has Python 3.14+ and `pyenv` bootstrap is unavailable or fails.
- If you want to keep the app private, do not publish port `8501` beyond your reverse proxy or SSH tunnel.
- If you do publish it, terminate HTTPS at the proxy and enable the built-in `APP_AUTH_*` gate.
- Depending on your repository and package settings, you may need to make the first GHCR package public in GitHub Packages before anonymous pulls work.
