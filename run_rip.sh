#!/usr/bin/env bash
set -e

if command -v rip >/dev/null 2>&1; then
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    rip --quality 3 url "$url"
  done < "exports/qobuz_batch_01.txt"
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    rip --quality 3 url "$url"
  done < "exports/qobuz_batch_02.txt"
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    rip --quality 3 url "$url"
  done < "exports/qobuz_batch_03.txt"
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    rip --quality 3 url "$url"
  done < "exports/qobuz_batch_04.txt"
elif python -m streamrip --help >/dev/null 2>&1; then
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    python -m streamrip --quality 3 url "$url"
  done < "exports/qobuz_batch_01.txt"
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    python -m streamrip --quality 3 url "$url"
  done < "exports/qobuz_batch_02.txt"
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    python -m streamrip --quality 3 url "$url"
  done < "exports/qobuz_batch_03.txt"
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    python -m streamrip --quality 3 url "$url"
  done < "exports/qobuz_batch_04.txt"
else
  echo "Streamrip not found. Install with: pip install streamrip"
  exit 1
fi

printf '\nPress Enter to exit...'; read -r _
