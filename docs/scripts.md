# Script Reference

## Launchers

- `run.sh`: Linux and generic POSIX shell launcher. Uses `python` or `python3`, recreates incomplete `.venv` environments, installs dependencies, warns if Qobuz auth is missing, then runs Streamlit.
- `run.command`: macOS Finder-friendly wrapper around `run.sh`.
- `run.bat`: Windows launcher with the same dependency/bootstrap flow as `run.sh`, using `python` or `py -3`.

Python 3.14 note:

- the launchers still start the core app on Python 3.14+, but the optional `streamrip` CLI dependency is skipped there until upstream publishes compatible builds

## Hosting Helper

- `setup-hbd.sh`: Provisioning helper for HostingByDesign-style boxes. Finds or bootstraps a Python 3.10+ runtime, creates a userland virtualenv, installs dependencies, writes a user `systemd` unit, stores the chosen port, and optionally starts the service.

## Export Helpers

The app generates these on demand in the repo root after export actions:

- `run_rip.sh`
- `run_rip.bat`

Those helper scripts read the per-export Qobuz batch files from `exports/`.
