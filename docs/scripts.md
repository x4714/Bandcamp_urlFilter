# Script Reference

## Launchers

- `run.sh`: Linux and generic POSIX shell launcher. Prefers Python `3.13 -> 3.9`, bootstraps `pyenv` automatically when only incompatible interpreters are present (for example only 3.14), recreates incomplete `.venv` environments, installs dependencies, warns if Qobuz auth is missing, then runs Streamlit.
- `run.command`: macOS Finder-friendly wrapper around `run.sh`.
- `run.bat`: Windows launcher with the same dependency/bootstrap flow as `run.sh`, preferring installed `py -3.13 .. -3.9` or a compatible `python` executable.

Python compatibility note:

- launcher-managed virtualenvs are pinned to Python 3.9-3.13
- bundled `streamrip` install is enabled on Python 3.10-3.13

## Hosting Helper

- `setup-hbd.sh`: Provisioning helper for HostingByDesign-style boxes. Finds or bootstraps a Python 3.9-3.13 runtime, creates a userland virtualenv, installs dependencies, can offer optional built-in app auth for public-facing domains, writes a user `systemd` unit, stores the chosen port, and optionally starts the service.

## Export Helpers

The app generates these on demand in the repo root after export actions:

- `run_rip.sh`
- `run_rip.bat`

Those helper scripts read the per-export Qobuz batch files from `exports/`.
