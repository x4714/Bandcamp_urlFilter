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

Add `QOBUZ_USER_AUTH_TOKEN` to `.env` for live Qobuz matching.

Optional extras you can also keep in `.env`:

- `QOBUZ_APP_ID` if you want to pin it instead of relying on auto-discovery
- `APP_AUTH_ENABLED`, `APP_AUTH_USERNAME`, and `APP_AUTH_PASSWORD_HASH` if the app will be reachable on the public web
- `APP_AUTH_SESSION_TTL_SECONDS`, `APP_AUTH_MAX_FAILURES`, and `APP_AUTH_LOCKOUT_SECONDS` if you want to tune session expiry or lockout behavior
- `RED_API_KEY` / `RED_SESSION_COOKIE` and `OPS_API_KEY` / `OPS_SESSION_COOKIE` for duplicate checking and upload helpers
- `RED_URL` and `OPS_URL` if you use non-default tracker domains

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
- Docker is currently the easiest way to keep the full rip/download workflow available if your host machine is using Python 3.14+.
- If you want to keep the app private, do not publish port `8501` beyond your reverse proxy or SSH tunnel.
- If you do publish it, terminate HTTPS at the proxy and enable the built-in `APP_AUTH_*` gate.
- Depending on your repository and package settings, you may need to make the first GHCR package public in GitHub Packages before anonymous pulls work.

