# HostingByDesign Setup

This repo now ships with `setup-hbd.sh`, a Linux helper intended for HostingByDesign and similar userland boxes where you want:

- a reusable Python virtual environment
- a user `systemd` service
- a stable Streamlit port
- no root-only install steps

Important Python note:

- the app requires Python 3.10 or newer
- many HostingByDesign boxes expose `python3.9.2` by default, which is too old for this repo
- `setup-hbd.sh` searches for `python3.13`, `python3.12`, `python3.11`, `python3.10`, then falls back to `python3` / `python`
- if no suitable interpreter is found, the script now bootstraps `pyenv` into `~/.local/opt/pyenv` and builds a userland Python automatically
- if you already have a newer interpreter under a specific name, you can force it with `PYTHON_BIN=python3.11 ./setup-hbd.sh`
- if you do not want the `pyenv` fallback, run `./setup-hbd.sh --skip-pyenv-bootstrap`
- if `pyenv` cannot build Python because the box is missing compiler dependencies, use Docker or point the script at a host-provided Python 3.10+ binary

## What the script does

Running `./setup-hbd.sh` will:

1. find a Python 3.10+ interpreter, or bootstrap one with `pyenv` if needed
2. create or reuse `~/.config/venv/bandcamp-urlfilter`
3. install `requirements.txt`
4. create `.env` from `.env.example` if it does not exist yet
5. pick an available port from `8501-8999` unless you provide one
6. write a user service to `~/.config/systemd/user/bandcamp-urlfilter.service`
7. enable and start the service with `systemctl --user`

The script also stores its resolved settings in `~/.config/bandcamp-urlfilter/install.env`.

## Quick Start

```bash
git clone https://github.com/HauZ22/Bandcamp_urlFilter.git
cd Bandcamp_urlFilter
chmod +x setup-hbd.sh
./setup-hbd.sh
```

After that, edit `.env` and add at least:

```env
QOBUZ_USER_AUTH_TOKEN=your_token_here
```

Then restart the service:

```bash
systemctl --user restart bandcamp-urlfilter
```

## Common Options

Use a fixed port:

```bash
./setup-hbd.sh --port 8765
```

Expose the app on all interfaces instead of localhost:

```bash
./setup-hbd.sh --bind 0.0.0.0
```

Write the service but do not start it yet:

```bash
./setup-hbd.sh --no-start
```

Disable automatic `pyenv` bootstrap:

```bash
./setup-hbd.sh --skip-pyenv-bootstrap
```

## Accessing the App

By default the service binds to `127.0.0.1`. That is the safer default for shared boxes.

Use an SSH tunnel from your local machine:

```bash
ssh -N -L 8501:127.0.0.1:8501 username@your-box
```

Replace both `8501` values if your setup script chose or was given a different port.

## Service Management

```bash
systemctl --user status bandcamp-urlfilter
systemctl --user restart bandcamp-urlfilter
journalctl --user -u bandcamp-urlfilter -f
```

## Notes

- `PYTHONPATH` is set to the repo root in the service so local modules import correctly.
- Streamrip config will live under `~/.config/streamrip/config.toml` unless you override `XDG_CONFIG_HOME`.
- The app writes exported URL batches inside the repo's `exports/` directory and writes `run_rip.sh` / `run_rip.bat` at the repo root.
- `smoked-salmon` is intentionally not installed from this repo's `requirements.txt`; install it separately with `uv tool install git+https://github.com/smokin-salmon/smoked-salmon`.
