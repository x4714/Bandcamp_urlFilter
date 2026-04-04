#!/usr/bin/env bash
set -e

# macOS-friendly launcher (double-clickable in Finder).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

chmod +x ./run.sh 2>/dev/null || true
exec ./run.sh
