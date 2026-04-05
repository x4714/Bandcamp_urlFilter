import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from dotenv import load_dotenv

QUALITY_OPTIONS = [0, 1, 2, 3, 4]
QUALITY_LABELS = {
    0: "0 - 128 kbps MP3/AAC",
    1: "1 - 320 kbps MP3/AAC",
    2: "2 - 16 bit / 44.1 kHz (CD)",
    3: "3 - 24 bit / up to 96 kHz",
    4: "4 - 24 bit / up to 192 kHz",
}
CODEC_OPTIONS = ["Original", "MP3", "FLAC", "ALAC", "OPUS", "VORBIS", "AAC"]


def format_quality_option(quality: int) -> str:
    return QUALITY_LABELS.get(quality, str(quality))


def normalize_codec_selection(codec_selection: str) -> str:
    normalized = codec_selection.strip().upper()
    if normalized in ("", "ORIGINAL", "SOURCE"):
        return ""
    return normalized


def get_env_qobuz_values() -> tuple[str, str]:
    load_dotenv(override=True)
    app_id = os.getenv("QOBUZ_APP_ID", "").strip()
    token = os.getenv("QOBUZ_USER_AUTH_TOKEN", "").strip()
    return app_id, token


def get_streamrip_config_path() -> str:
    try:
        from streamrip.config import DEFAULT_CONFIG_PATH  # type: ignore

        return str(DEFAULT_CONFIG_PATH)
    except Exception:
        if os.name == "nt":
            appdata = os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
            return os.path.join(appdata, "streamrip", "config.toml")
        if sys.platform == "darwin":
            return os.path.join(
                os.path.expanduser("~"),
                "Library",
                "Application Support",
                "streamrip",
                "config.toml",
            )
        config_home = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(config_home, "streamrip", "config.toml")


def ensure_streamrip_config_file(config_path: str) -> tuple[bool, str]:
    if os.path.exists(config_path):
        return True, ""

    try:
        from streamrip.config import BLANK_CONFIG_PATH  # type: ignore

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        shutil.copyfile(str(BLANK_CONFIG_PATH), config_path)
        return True, f"Created streamrip config at `{config_path}`."
    except Exception as e:
        return False, f"Could not initialize streamrip config: {e}"


def load_streamrip_settings(config_path: str) -> tuple[dict, str]:
    if not os.path.exists(config_path):
        return {}, "Streamrip config file not found."

    try:
        from streamrip.config import Config  # type: ignore

        config = Config(config_path)
        qobuz = config.file.qobuz
        conversion = config.file.conversion

        codec_selection = conversion.codec.upper() if conversion.enabled else "Original"
        if codec_selection not in CODEC_OPTIONS:
            codec_selection = "Original"

        return {
            "use_auth_token": bool(qobuz.use_auth_token),
            "email_or_userid": qobuz.email_or_userid or "",
            "password_or_token": qobuz.password_or_token or "",
            "app_id": qobuz.app_id or "",
            "quality": int(qobuz.quality),
            "codec_selection": codec_selection,
            "downloads_folder": config.file.downloads.folder or "",
        }, ""
    except Exception as e:
        return {}, f"Could not read streamrip config: {e}"


def save_streamrip_settings(
    config_path: str,
    use_auth_token: bool,
    email_or_userid: str,
    password_or_token: str,
    app_id: str,
    quality: int,
    codec_selection: str,
    downloads_folder: str = "",
) -> tuple[bool, str]:
    try:
        from streamrip.config import Config  # type: ignore

        config = Config(config_path)
        file_data = config.file

        file_data.qobuz.use_auth_token = bool(use_auth_token)
        file_data.qobuz.email_or_userid = email_or_userid.strip()

        token_value = password_or_token.strip()
        if token_value:
            file_data.qobuz.password_or_token = token_value

        app_id_value = app_id.strip()
        if app_id_value:
            file_data.qobuz.app_id = app_id_value

        file_data.qobuz.quality = int(quality)
        selected_codec = normalize_codec_selection(codec_selection)
        file_data.conversion.enabled = bool(selected_codec)
        if selected_codec:
            file_data.conversion.codec = selected_codec
        if downloads_folder.strip():
            file_data.downloads.folder = downloads_folder.strip()

        file_data.set_modified()
        config.save_file()
        return True, "Streamrip config updated."
    except Exception as e:
        return False, f"Could not save streamrip config: {e}"


def read_streamrip_config_text(config_path: str, show_secrets: bool = False) -> str:
    if not os.path.exists(config_path):
        return "Config file not found."

    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()

    if show_secrets:
        return text

    text = re.sub(r'(password_or_token\s*=\s*)".*?"', r'\1"***"', text)
    return text


def fetch_qobuz_user_identifier(app_id: str, user_token: str) -> tuple[bool, dict, str]:
    app_id = app_id.strip()
    user_token = user_token.strip()
    if not app_id or not user_token:
        return False, {}, "Need both Qobuz App ID and user auth token."

    url = "https://www.qobuz.com/api.json/0.2/user/login"
    headers = {
        "accept": "*/*",
        "content-type": "text/plain;charset=UTF-8",
        "origin": "https://play.qobuz.com",
        "referer": "https://play.qobuz.com/",
        "x-app-id": app_id,
        "x-user-auth-token": user_token,
    }
    payload = b"extra=partner"
    request = urlrequest.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urlrequest.urlopen(request, timeout=15) as response:
            status = response.getcode()
            body = response.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return False, {}, f"Qobuz lookup failed with HTTP {e.code}: {body[:180]}"
    except Exception as e:
        return False, {}, f"Qobuz lookup failed: {e}"

    if status != 200:
        return False, {}, f"Qobuz lookup failed with HTTP {status}: {body[:180]}"

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False, {}, "Qobuz response was not valid JSON."

    user = data.get("user", {}) if isinstance(data, dict) else {}
    user_id = user.get("id") or user.get("user_id") or data.get("user_id", "")
    email = user.get("email") or data.get("email", "")
    login = user.get("login") or user.get("slug") or ""

    identifier = ""
    for candidate in (user_id, login, email):
        candidate_str = str(candidate).strip()
        if candidate_str:
            identifier = candidate_str
            break

    if not identifier:
        return False, {}, "Could not find user identifier in Qobuz response."

    return True, {
        "identifier": identifier,
        "email": str(email).strip(),
        "user_id": str(user_id).strip(),
        "login": str(login).strip(),
    }, "Fetched Qobuz user identifier."


def resolve_streamrip_command() -> List[str]:
    rip_bin = shutil.which("rip")
    if rip_bin:
        return [rip_bin]

    probe = subprocess.run(
        [sys.executable, "-m", "streamrip", "--help"],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "streamrip"]
    return []


def run_streamrip_batches(
    batch_files: List[str],
    rip_quality: int,
    codec_selection: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[int, int, List[str], str]:
    base_cmd = resolve_streamrip_command()
    log_path = os.path.abspath(os.path.join("exports", "streamrip_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    streamrip_timeout_seconds = 1800
    codec_arg = normalize_codec_selection(codec_selection)

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"Streamrip run started: {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"Interpreter: {sys.executable}\n")
        log.write(f"Base command: {' '.join(base_cmd) if base_cmd else 'NOT FOUND'}\n\n")
        log.write(f"Selected quality: {rip_quality} ({format_quality_option(rip_quality)})\n")
        log.write(f"Selected codec: {codec_arg or 'Original'}\n\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if not base_cmd:
        return 0, 0, [
            f"Streamrip not found for interpreter: {sys.executable}",
            f"Install with: {sys.executable} -m pip install streamrip",
        ], log_path

    success_count = 0
    total_urls = 0
    failures: List[str] = []
    for fname in batch_files:
        rel_path = os.path.join("exports", fname)
        try:
            with open(rel_path, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip()]
        except Exception as e:
            failures.append(f"{fname}: could not read batch file ({e})")
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[{fname}] read error: {e}\n")
            continue

        if not urls:
            failures.append(f"{fname}: no URLs found")
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[{fname}] no URLs found\n")
            continue

        total_urls += len(urls)
        file_failed = False
        for url in urls:
            cmd = [*base_cmd, "--quality", str(rip_quality)]
            if codec_arg:
                cmd.extend(["--codec", codec_arg.lower()])
            cmd.extend(["url", url])
            log_offset_before = os.path.getsize(log_path)
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[start] {datetime.now(timezone.utc).isoformat()} :: {fname} :: {url}\n")
                log.flush()
            process = None
            try:
                with open(log_path, "a", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        cmd,
                        stdout=log,
                        stderr=log,
                        stdin=subprocess.DEVNULL,
                        text=True,
                    )
                started_at = time.monotonic()
                while True:
                    remaining = streamrip_timeout_seconds - (time.monotonic() - started_at)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(cmd, streamrip_timeout_seconds)
                    wait_for = min(0.75, remaining)
                    try:
                        result_code = process.wait(timeout=wait_for)
                        break
                    except subprocess.TimeoutExpired:
                        if progress_callback:
                            progress_callback(log_path, _read_log_tail(log_path))
            except subprocess.TimeoutExpired:
                if process is not None:
                    process.kill()
                    process.wait()
                with open(log_path, "a", encoding="utf-8") as log:
                    log.write(
                        f"[timeout] {datetime.now(timezone.utc).isoformat()} :: {' '.join(cmd)}\n\n"
                    )
                failures.append(
                    f"{fname}: {url} -> timed out after {streamrip_timeout_seconds}s"
                )
                file_failed = True
                if progress_callback:
                    progress_callback(log_path, _read_log_tail(log_path))
                continue

            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"$ {' '.join(cmd)}\n")
                log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n\n")
            if progress_callback:
                progress_callback(log_path, _read_log_tail(log_path))
            if result_code != 0:
                with open(log_path, "r", encoding="utf-8") as log_read:
                    log_read.seek(log_offset_before)
                    recent_output = log_read.read().lower()
                if "enter your qobuz email" in recent_output or "enter your qobuz password" in recent_output:
                    failures.append(
                        f"{fname}: {url} -> Streamrip is not configured. "
                        "Open 'Streamrip Setup' in the Web UI and set Qobuz credentials "
                        "(or run `rip config open`)."
                    )
                else:
                    failures.append(f"{fname}: {url} -> exit code {result_code}")
                file_failed = True

        if not file_failed:
            success_count += 1

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(
            f"Streamrip run finished: {datetime.now(timezone.utc).isoformat()} "
            f"(batches_ok={success_count}, urls={total_urls}, failures={len(failures)})\n"
        )
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    return success_count, total_urls, failures, log_path


def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def list_export_batch_files() -> List[str]:
    export_dir = os.path.abspath("exports")
    if not os.path.isdir(export_dir):
        return []
    return sorted(
        f
        for f in os.listdir(export_dir)
        if f.startswith("qobuz_batch_") and f.endswith(".txt")
    )


def export_qobuz_batches(valid_urls: List[str], max_links: int, rip_quality: int, rip_codec: str) -> tuple[List[str], int]:
    export_dir = os.path.abspath("exports")
    os.makedirs(export_dir, exist_ok=True)

    batch_files = []
    total_batches = (len(valid_urls) + max_links - 1) // max_links

    for i in range(total_batches):
        batch_urls = valid_urls[i * max_links : (i + 1) * max_links]
        batch_num = f"{i + 1:02d}"
        filename = f"qobuz_batch_{batch_num}.txt"
        filepath = os.path.join(export_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(batch_urls) + "\n")

        batch_files.append(filename)

    bat_path = os.path.abspath("run_rip.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        rip_flags = f"--quality {rip_quality}"
        codec_arg = normalize_codec_selection(rip_codec)
        if codec_arg:
            rip_flags += f" --codec {codec_arg.lower()}"
        f.write("@echo off\n")
        f.write("setlocal\n")
        f.write("where rip >nul 2>nul\n")
        f.write("if not errorlevel 1 (\n")
        for fname in batch_files:
            f.write(f"  for /f \"usebackq delims=\" %%U in (\"exports/{fname}\") do (\n")
            f.write(f"    if not \"%%U\"==\"\" call rip {rip_flags} url \"%%U\"\n")
            f.write("  )\n")
        f.write(") else (\n")
        f.write("  python -m streamrip --help >nul 2>nul\n")
        f.write("  if errorlevel 1 (\n")
        f.write('    echo Streamrip not found. Install with: pip install streamrip\n')
        f.write("    pause\n")
        f.write("    exit /b 1\n")
        f.write("  )\n")
        for fname in batch_files:
            f.write(f"  for /f \"usebackq delims=\" %%U in (\"exports/{fname}\") do (\n")
            f.write(f"    if not \"%%U\"==\"\" python -m streamrip {rip_flags} url \"%%U\"\n")
            f.write("  )\n")
        f.write(")\n")
        f.write("pause\n")

    sh_path = os.path.abspath("run_rip.sh")
    with open(sh_path, "w", encoding="utf-8") as f:
        rip_flags = f"--quality {rip_quality}"
        codec_arg = normalize_codec_selection(rip_codec)
        if codec_arg:
            rip_flags += f" --codec {codec_arg.lower()}"
        f.write("#!/usr/bin/env bash\n")
        f.write("set -e\n\n")
        f.write("if command -v rip >/dev/null 2>&1; then\n")
        for fname in batch_files:
            f.write("  while IFS= read -r url; do\n")
            f.write("    [ -z \"$url\" ] && continue\n")
            f.write(f"    rip {rip_flags} url \"$url\"\n")
            f.write(f"  done < \"exports/{fname}\"\n")
        f.write("elif python -m streamrip --help >/dev/null 2>&1; then\n")
        for fname in batch_files:
            f.write("  while IFS= read -r url; do\n")
            f.write("    [ -z \"$url\" ] && continue\n")
            f.write(f"    python -m streamrip {rip_flags} url \"$url\"\n")
            f.write(f"  done < \"exports/{fname}\"\n")
        f.write("else\n")
        f.write('  echo "Streamrip not found. Install with: pip install streamrip"\n')
        f.write("  exit 1\n")
        f.write("fi\n\n")
        f.write("printf '\\nPress Enter to exit...'; read -r _\n")

    try:
        os.chmod(sh_path, 0o755)
    except Exception:
        pass

    return batch_files, total_batches
