import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from dotenv import load_dotenv
from app_modules.debug_logging import emit_debug

QUALITY_OPTIONS = [0, 1, 2, 3, 4]
QUALITY_LABELS = {
    0: "0 - 128 kbps MP3/AAC",
    1: "1 - 320 kbps MP3/AAC",
    2: "2 - 16 bit / 44.1 kHz (CD)",
    3: "3 - 24 bit / up to 96 kHz",
    4: "4 - 24 bit / up to 192 kHz",
}
CODEC_OPTIONS = ["Original", "MP3", "FLAC", "ALAC", "OPUS", "VORBIS", "AAC"]
QOBUZ_URL_REGEX = re.compile(r"https?://(?:www\.|play\.)?qobuz\.com/[^\s\"'<>]+", re.IGNORECASE)
_AUTO_DISCOVERED_APP_ID: str = ""
_AUTO_DISCOVER_CONDITION = threading.Condition()
_AUTO_DISCOVER_IN_FLIGHT = False
_AUTO_DISCOVER_WAITERS = 0
_AUTO_DISCOVER_LAST_STATUS = ""
_AUTO_DISCOVER_STATUS_SEQ = 0


def _streamrip_debug(message: str) -> None:
    emit_debug("streamrip", message)


def _bundle_debug(message: str) -> None:
    _streamrip_debug(f"[bundle] {message}")


def _publish_discovery_status(message: str, local_callback: Optional[Callable[[str], None]] = None) -> None:
    global _AUTO_DISCOVER_LAST_STATUS, _AUTO_DISCOVER_STATUS_SEQ
    with _AUTO_DISCOVER_CONDITION:
        _AUTO_DISCOVER_LAST_STATUS = message
        _AUTO_DISCOVER_STATUS_SEQ += 1
        _AUTO_DISCOVER_CONDITION.notify_all()
    if local_callback:
        try:
            local_callback(message)
        except Exception:
            pass


def get_default_downloads_folder() -> str:
    home = os.path.expanduser("~")
    music_folder = os.path.join(home, "Music")
    if os.path.isdir(music_folder):
        return music_folder
    return home


def is_streamrip_installed() -> bool:
    return bool(resolve_streamrip_command())


def format_eta(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_quality_option(quality: int) -> str:
    return QUALITY_LABELS.get(quality, str(quality))


def normalize_codec_selection(codec_selection: str) -> str:
    normalized = codec_selection.strip().upper()
    if normalized in ("", "ORIGINAL", "SOURCE"):
        return ""
    return normalized


def extract_qobuz_urls(raw_text: str) -> List[str]:
    if not raw_text:
        return []

    seen = set()
    urls: List[str] = []
    for match in QOBUZ_URL_REGEX.findall(raw_text):
        cleaned = match.rstrip("),.;]}>\"'")
        if cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)
    return urls


def get_env_qobuz_values(status_callback=None) -> tuple[str, str]:
    _streamrip_debug("get_env_qobuz_values() called.")
    if status_callback:
        status_callback("Loading variables from .env...")
    load_dotenv(override=True)

    if status_callback:
        status_callback("Reading QOBUZ_APP_ID and QOBUZ_USER_AUTH_TOKEN...")
    app_id = os.getenv("QOBUZ_APP_ID", "").strip()
    token = os.getenv("QOBUZ_USER_AUTH_TOKEN", "").strip()

    if not app_id:
        _streamrip_debug("QOBUZ_APP_ID missing in environment; starting auto-discovery.")
        if status_callback:
            status_callback("QOBUZ_APP_ID not set. Discovering from play.qobuz.com...")
        app_id = discover_qobuz_app_id(status_callback=status_callback)
    elif status_callback:
        status_callback("Using QOBUZ_APP_ID from .env.")
        _streamrip_debug("Using QOBUZ_APP_ID from environment.")

    if status_callback:
        token_state = "found" if token else "missing"
        status_callback(f"QOBUZ_USER_AUTH_TOKEN {token_state}.")
    _streamrip_debug(
        f"Qobuz env values resolved. app_id_present={bool(app_id)}, token_present={bool(token)}"
    )
    return app_id, token


def discover_qobuz_app_id(status_callback=None) -> str:
    global _AUTO_DISCOVERED_APP_ID, _AUTO_DISCOVER_IN_FLIGHT, _AUTO_DISCOVER_WAITERS
    discover_started_at = time.monotonic()
    with _AUTO_DISCOVER_CONDITION:
        if _AUTO_DISCOVERED_APP_ID:
            _bundle_debug("Returning cached auto-discovered Qobuz App ID.")
            if status_callback:
                status_callback("Using cached auto-discovered Qobuz App ID.")
            return _AUTO_DISCOVERED_APP_ID

        if _AUTO_DISCOVER_IN_FLIGHT:
            _AUTO_DISCOVER_WAITERS += 1
            waiter_position = _AUTO_DISCOVER_WAITERS
            if waiter_position == 1 or waiter_position % 5 == 0:
                _bundle_debug(f"Discovery already in progress; waiters={_AUTO_DISCOVER_WAITERS}.")
            if status_callback:
                status_callback("Waiting for shared Qobuz App ID discovery...")
            last_seen_status_seq = _AUTO_DISCOVER_STATUS_SEQ
            while _AUTO_DISCOVER_IN_FLIGHT:
                _AUTO_DISCOVER_CONDITION.wait(timeout=0.25)
                if status_callback and _AUTO_DISCOVER_STATUS_SEQ != last_seen_status_seq:
                    message = _AUTO_DISCOVER_LAST_STATUS
                    last_seen_status_seq = _AUTO_DISCOVER_STATUS_SEQ
                    # Call each waiting thread's callback from its own thread context.
                    _AUTO_DISCOVER_CONDITION.release()
                    try:
                        if message:
                            status_callback(message)
                    finally:
                        _AUTO_DISCOVER_CONDITION.acquire()
            _AUTO_DISCOVER_WAITERS = max(0, _AUTO_DISCOVER_WAITERS - 1)
            if _AUTO_DISCOVERED_APP_ID:
                if status_callback:
                    status_callback("Using shared auto-discovered Qobuz App ID.")
                return _AUTO_DISCOVERED_APP_ID

        _AUTO_DISCOVER_IN_FLIGHT = True
        _bundle_debug("discover_qobuz_app_id() started (leader thread).")

    try:
        try:
            page_started_at = time.monotonic()
            _publish_discovery_status("Fetching Qobuz web player page...", local_callback=status_callback)
            _bundle_debug("Requesting https://play.qobuz.com/ ...")
            req = urlrequest.Request(
                "https://play.qobuz.com/",
                headers={
                    "user-agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
                    )
                },
            )
            with urlrequest.urlopen(req, timeout=12) as response:
                if response.getcode() != 200:
                    _bundle_debug(f"Web player page request failed with HTTP {response.getcode()}.")
                    return ""
                _bundle_debug(
                    f"Web player page fetched with HTTP {response.getcode()} in {time.monotonic() - page_started_at:.3f}s."
                )
                html = response.read().decode("utf-8", errors="replace")
        except Exception:
            _bundle_debug("Exception while fetching Qobuz web player page.")
            return ""

        _publish_discovery_status("Extracting bundle.js URL from player page...", local_callback=status_callback)
        bundle_match = re.search(r'src="(/resources/[^"]*bundle\.js)"', html)
        if not bundle_match:
            _bundle_debug("Could not find bundle.js URL in player HTML.")
            return ""

        bundle_url = f"https://play.qobuz.com{bundle_match.group(1)}"
        _bundle_debug(f"Discovered bundle.js URL: {bundle_url}")
        try:
            request_started_at = time.monotonic()
            _publish_discovery_status("Preparing bundle.js request...", local_callback=status_callback)
            req = urlrequest.Request(
                bundle_url,
                headers={
                    "user-agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
                    )
                },
            )
            _publish_discovery_status("Opening connection to Qobuz bundle.js...", local_callback=status_callback)
            _bundle_debug("Opening bundle.js connection...")
            with urlrequest.urlopen(req, timeout=12) as response:
                if response.getcode() != 200:
                    _bundle_debug(f"bundle.js request failed with HTTP {response.getcode()}.")
                    return ""
                _bundle_debug(
                    f"bundle.js response opened with HTTP {response.getcode()} in {time.monotonic() - request_started_at:.3f}s."
                )
                _publish_discovery_status("Reading Qobuz bundle.js response headers...", local_callback=status_callback)
                content_length_header = response.headers.get("Content-Length", "").strip()
                expected_bytes = int(content_length_header) if content_length_header.isdigit() else 0
                _bundle_debug(
                    f"bundle.js headers read. Content-Length={expected_bytes if expected_bytes > 0 else 'unknown'}."
                )

                if expected_bytes > 0:
                    _publish_discovery_status(
                        f"Starting bundle.js download (expected {expected_bytes:,} bytes)...",
                        local_callback=status_callback,
                    )
                else:
                    _publish_discovery_status("Starting bundle.js download (size unknown)...", local_callback=status_callback)

                chunks: list[bytes] = []
                downloaded_bytes = 0
                report_every_bytes = 256 * 1024
                next_report_at = report_every_bytes
                download_started_at = time.monotonic()
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes >= next_report_at:
                        if expected_bytes > 0:
                            percent = (downloaded_bytes / expected_bytes) * 100
                            elapsed = max(0.001, time.monotonic() - download_started_at)
                            speed_bps = downloaded_bytes / elapsed
                            remaining_bytes = max(0, expected_bytes - downloaded_bytes)
                            eta_text = ""
                            if speed_bps > 0 and remaining_bytes > 0:
                                eta_text = f" | ETA {format_eta(remaining_bytes / speed_bps)}"
                            _publish_discovery_status(
                                f"Downloading bundle.js... {downloaded_bytes:,}/{expected_bytes:,} bytes ({percent:.1f}%){eta_text}"
                                ,
                                local_callback=status_callback,
                            )
                        else:
                            _publish_discovery_status(
                                f"Downloading bundle.js... {downloaded_bytes:,} bytes",
                                local_callback=status_callback,
                            )
                        next_report_at += report_every_bytes

                raw_js = b"".join(chunks)
                download_elapsed = max(0.001, time.monotonic() - download_started_at)
                avg_speed_mib_s = (downloaded_bytes / download_elapsed) / (1024 * 1024)
                _bundle_debug(
                    f"bundle.js download complete: {downloaded_bytes:,} bytes in {download_elapsed:.3f}s "
                    f"(avg {avg_speed_mib_s:.2f} MiB/s)."
                )
                if expected_bytes > 0:
                    _publish_discovery_status(
                        f"Bundle.js download complete ({downloaded_bytes:,}/{expected_bytes:,} bytes).",
                        local_callback=status_callback,
                    )
                else:
                    _publish_discovery_status(
                        f"Bundle.js download complete ({downloaded_bytes:,} bytes).",
                        local_callback=status_callback,
                    )
                _publish_discovery_status("Decoding Qobuz bundle.js content...", local_callback=status_callback)
                decode_started_at = time.monotonic()
                js = raw_js.decode("utf-8", errors="replace")
                _bundle_debug(
                    f"bundle.js decoded in {time.monotonic() - decode_started_at:.3f}s "
                    f"(decoded length={len(js):,} chars)."
                )
        except Exception as e:
            _bundle_debug(f"Exception while downloading/decoding bundle.js: {e}")
            return ""

        _publish_discovery_status("Parsing App ID from bundle.js...", local_callback=status_callback)
        parse_started_at = time.monotonic()
        production_match = re.search(
            r'"?production"?\s*:\s*\{.*?"?api"?\s*:\s*\{.*?"?appId"?\s*:\s*"(\d+)"',
            js,
            re.DOTALL,
        )
        if not production_match:
            _bundle_debug("Could not parse Qobuz App ID from bundle.js.")
            return ""
        _bundle_debug(f"Parsed Qobuz App ID in {time.monotonic() - parse_started_at:.3f}s.")

        _AUTO_DISCOVERED_APP_ID = production_match.group(1)
        _publish_discovery_status("Qobuz App ID discovered from web player.", local_callback=status_callback)
        _bundle_debug(
            f"Qobuz App ID discovered successfully in {time.monotonic() - discover_started_at:.3f}s total."
        )
        return _AUTO_DISCOVERED_APP_ID
    finally:
        with _AUTO_DISCOVER_CONDITION:
            _AUTO_DISCOVER_IN_FLIGHT = False
            waiter_count = _AUTO_DISCOVER_WAITERS
            if waiter_count:
                _bundle_debug(f"Discovery complete; notifying {waiter_count} waiting thread(s).")
            _AUTO_DISCOVER_CONDITION.notify_all()


def get_streamrip_config_path() -> str:
    _streamrip_debug("Resolving streamrip config path.")
    try:
        from streamrip.config import DEFAULT_CONFIG_PATH  # type: ignore

        resolved = str(DEFAULT_CONFIG_PATH)
        _streamrip_debug(f"Using streamrip DEFAULT_CONFIG_PATH: `{resolved}`")
        return resolved
    except Exception:
        if os.name == "nt":
            appdata = os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
            resolved = os.path.join(appdata, "streamrip", "config.toml")
            _streamrip_debug(f"Using Windows fallback config path: `{resolved}`")
            return resolved
        if sys.platform == "darwin":
            resolved = os.path.join(
                os.path.expanduser("~"),
                "Library",
                "Application Support",
                "streamrip",
                "config.toml",
            )
            _streamrip_debug(f"Using macOS fallback config path: `{resolved}`")
            return resolved
        config_home = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        resolved = os.path.join(config_home, "streamrip", "config.toml")
        _streamrip_debug(f"Using Linux fallback config path: `{resolved}`")
        return resolved





def get_streamrip_database_defaults(config_path: str) -> tuple[str, str]:
    config_dir = os.path.dirname(os.path.abspath(os.path.expanduser(config_path)))
    downloads_db = os.path.join(config_dir, "downloads.db")
    failed_dir = os.path.join(config_dir, "failed")
    _streamrip_debug(
        f"Database defaults resolved for `{config_path}` -> db=`{downloads_db}`, failed=`{failed_dir}`"
    )
    return downloads_db, failed_dir




def ensure_streamrip_config_file(config_path: str) -> tuple[bool, str]:
    _streamrip_debug(f"Ensuring streamrip config file exists at `{config_path}`.")
    if os.path.exists(config_path):
        _streamrip_debug("Config file already exists; no initialization required.")
        return True, ""

    try:
        from streamrip.config import BLANK_CONFIG_PATH  # type: ignore

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        shutil.copyfile(str(BLANK_CONFIG_PATH), config_path)
        _streamrip_debug(f"Created streamrip config from BLANK_CONFIG_PATH at `{config_path}`.")
        return True, f"Created streamrip config at `{config_path}`."
    except Exception as e:
        _streamrip_debug(f"Failed to initialize streamrip config: {e}")
        return False, f"Could not initialize streamrip config: {e}"


def load_streamrip_settings(config_path: str) -> tuple[dict, str]:
    _streamrip_debug(f"Loading streamrip settings from `{config_path}`.")
    if not os.path.exists(config_path):
        _streamrip_debug("Streamrip config file missing while loading settings.")
        return {}, "Streamrip config file not found."

    try:
        from streamrip.config import Config  # type: ignore

        config = Config(config_path)
        qobuz = config.file.qobuz
        conversion = config.file.conversion
        default_db_path, default_failed_path = get_streamrip_database_defaults(config_path)

        codec_selection = conversion.codec.upper() if conversion.enabled else "Original"
        if codec_selection not in CODEC_OPTIONS:
            codec_selection = "Original"
        downloads_db_path = default_db_path
        failed_downloads_path = default_failed_path
        db_cfg = None
        if hasattr(config.file, "database"):
            db_cfg = config.file.database
        else:
            file_session: Any = getattr(config.file, "session", None)
            if file_session is not None and hasattr(file_session, "database"):
                db_cfg = file_session.database
            else:
                config_session: Any = getattr(config, "session", None)
                if config_session is not None and hasattr(config_session, "database"):
                    db_cfg = config_session.database

        if db_cfg:
            configured_db_path = str(getattr(db_cfg, "downloads_path", "") or "").strip()
            configured_failed_path = str(getattr(db_cfg, "failed_downloads_path", "") or "").strip()
            if configured_db_path:
                downloads_db_path = configured_db_path
            if configured_failed_path:
                failed_downloads_path = configured_failed_path
        if hasattr(config.file, "downloads"):
            downloads_cfg = config.file.downloads
            configured_failed_path = str(getattr(downloads_cfg, "failed_downloads_path", "") or "").strip()
            if configured_failed_path:
                failed_downloads_path = configured_failed_path

        downloads_folder = str(config.file.downloads.folder or "").strip()
        if not downloads_folder:
            downloads_folder = get_default_downloads_folder()
        settings = {
            "use_auth_token": bool(qobuz.use_auth_token),
            "email_or_userid": qobuz.email_or_userid or "",
            "password_or_token": qobuz.password_or_token or "",
            "app_id": qobuz.app_id or "",
            "quality": int(qobuz.quality),
            "codec_selection": codec_selection,
            "downloads_folder": downloads_folder,
            "downloads_db_path": downloads_db_path,
            "failed_downloads_path": failed_downloads_path,
        }
        _streamrip_debug(
            "Loaded streamrip settings "
            f"(use_auth_token={settings['use_auth_token']}, "
            f"quality={settings['quality']}, codec={settings['codec_selection']}, "
            f"downloads_folder_set={bool(settings['downloads_folder'])})."
        )
        return settings, ""
    except Exception as e:
        _streamrip_debug(f"Could not read streamrip config: {e}")
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
    downloads_db_path: str = "",
    failed_downloads_path: str = "",
) -> tuple[bool, str]:
    _streamrip_debug(f"Saving streamrip settings to `{config_path}`.")
    try:
        from streamrip.config import Config  # type: ignore

        config = Config(config_path)
        file_data = config.file
        default_db_path, default_failed_path = get_streamrip_database_defaults(config_path)
        selected_downloads_db_path = (
            os.path.abspath(os.path.expanduser(downloads_db_path.strip()))
            if downloads_db_path.strip()
            else default_db_path
        )
        selected_failed_downloads_path = (
            os.path.abspath(os.path.expanduser(failed_downloads_path.strip()))
            if failed_downloads_path.strip()
            else default_failed_path
        )
        os.makedirs(os.path.dirname(selected_downloads_db_path), exist_ok=True)
        os.makedirs(selected_failed_downloads_path, exist_ok=True)
        _streamrip_debug(
            "Prepared streamrip data paths: "
            f"downloads_db=`{selected_downloads_db_path}`, failed=`{selected_failed_downloads_path}`"
        )

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
        if hasattr(file_data, "downloads") and hasattr(file_data.downloads, "failed_downloads_path"):
            setattr(file_data.downloads, "failed_downloads_path", selected_failed_downloads_path)
        db_targets = []
        if hasattr(file_data, "database"):
            db_targets.append(file_data.database)
        file_session: Any = getattr(file_data, "session", None)
        if file_session is not None and hasattr(file_session, "database"):
            db_targets.append(file_session.database)
        config_session: Any = getattr(config, "session", None)
        if config_session is not None and hasattr(config_session, "database"):
            db_targets.append(config_session.database)

        # Ensure we set at least one database target
        for db_target in db_targets:
            if hasattr(db_target, "downloads_enabled"):
                db_target.downloads_enabled = True
            if hasattr(db_target, "downloads_path"):
                db_target.downloads_path = selected_downloads_db_path
            if hasattr(db_target, "failed_downloads_path"):
                db_target.failed_downloads_path = selected_failed_downloads_path

        file_data.set_modified()
        config.save_file()
        _streamrip_debug("Streamrip config saved successfully.")
        return True, "Streamrip config updated."
    except Exception as e:
        _streamrip_debug(f"Failed saving streamrip settings: {e}")
        return False, f"Could not save streamrip config: {e}"


def read_streamrip_config_text(config_path: str, show_secrets: bool = False) -> str:
    _streamrip_debug(
        f"Reading raw streamrip config text from `{config_path}` (show_secrets={show_secrets})."
    )
    if not os.path.exists(config_path):
        _streamrip_debug("Raw config read requested, but config file was not found.")
        return "Config file not found."

    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()

    if show_secrets:
        _streamrip_debug("Returning raw config with secrets visible.")
        return text

    text = re.sub(r'(password_or_token\s*=\s*)".*?"', r'\1"***"', text)
    _streamrip_debug("Returning masked raw config text.")
    return text


def fetch_qobuz_user_identifier(app_id: str, user_token: str) -> tuple[bool, dict, str]:
    _streamrip_debug("fetch_qobuz_user_identifier() called.")
    app_id = app_id.strip()
    user_token = user_token.strip()
    if not app_id or not user_token:
        _streamrip_debug("Cannot fetch identifier; app ID or token missing.")
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
        _streamrip_debug(f"Qobuz identifier lookup HTTP error: {e.code}")
        return False, {}, f"Qobuz lookup failed with HTTP {e.code}: {body[:180]}"
    except Exception as e:
        _streamrip_debug(f"Qobuz identifier lookup request failed: {e}")
        return False, {}, f"Qobuz lookup failed: {e}"

    if status != 200:
        _streamrip_debug(f"Qobuz identifier lookup returned non-200 status: {status}")
        return False, {}, f"Qobuz lookup failed with HTTP {status}: {body[:180]}"

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        _streamrip_debug("Qobuz identifier lookup returned non-JSON body.")
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
        _streamrip_debug("Qobuz identifier lookup succeeded but no identifier found in payload.")
        return False, {}, "Could not find user identifier in Qobuz response."

    _streamrip_debug(
        f"Fetched Qobuz identifier successfully (identifier=`{identifier}`, email_present={bool(email)})."
    )
    return True, {
        "identifier": identifier,
        "email": str(email).strip(),
        "user_id": str(user_id).strip(),
        "login": str(login).strip(),
    }, "Fetched Qobuz user identifier."


def resolve_streamrip_command() -> List[str]:
    _streamrip_debug("Resolving streamrip command.")
    rip_bin = shutil.which("rip")
    if rip_bin:
        _streamrip_debug(f"Using rip binary from PATH: `{rip_bin}`")
        return [rip_bin]

    probe = subprocess.run(
        [sys.executable, "-m", "streamrip", "--help"],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        _streamrip_debug("Using python -m streamrip fallback command.")
        return [sys.executable, "-m", "streamrip"]
    _streamrip_debug("Could not resolve streamrip command.")
    return []



def run_streamrip_batches(
    batch_files: List[str],
    rip_quality: int,
    codec_selection: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    status_callback: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[int, int, List[dict], List[dict], List[dict], str]:
    _streamrip_debug(
        f"run_streamrip_batches() called with {len(batch_files)} batch file(s), "
        f"quality={rip_quality}, codec={codec_selection}."
    )
    base_cmd = resolve_streamrip_command()
    log_path = os.path.abspath(os.path.join("exports", "streamrip_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    streamrip_timeout_seconds = 1800
    codec_arg = normalize_codec_selection(codec_selection)
    config_path = get_streamrip_config_path()
    streamrip_settings, streamrip_settings_error = load_streamrip_settings(config_path)
    downloads_folder = str(streamrip_settings.get("downloads_folder", "")).strip() if streamrip_settings else ""
    downloads_db_path = str(streamrip_settings.get("downloads_db_path", "")).strip() if streamrip_settings else ""
    failed_downloads_path = str(streamrip_settings.get("failed_downloads_path", "")).strip() if streamrip_settings else ""

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"Streamrip run started: {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"Interpreter: {sys.executable}\n")
        log.write(f"Base command: {' '.join(base_cmd) if base_cmd else 'NOT FOUND'}\n\n")
        log.write(f"Selected quality: {rip_quality} ({format_quality_option(rip_quality)})\n")
        log.write(f"Selected codec: {codec_arg or 'Original'}\n\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if not base_cmd:
        return 0, 0, [{"Batch": "Init", "URL": "N/A", "Reason": "Streamrip not found for interpreter"}], [], [], log_path
    if not downloads_folder:
        return 0, 0, [{"Batch": "Setup", "URL": "N/A", "Reason": "Streamrip Downloads Folder Path is blank."}], [], [], log_path
    if not downloads_db_path:
        return 0, 0, [{"Batch": "Setup", "URL": "N/A", "Reason": "Streamrip downloads database path is blank."}], [], [], log_path
    if not failed_downloads_path:
        return 0, 0, [{"Batch": "Setup", "URL": "N/A", "Reason": "Streamrip failed downloads path is blank."}], [], [], log_path
    if streamrip_settings_error:
        return 0, 0, [{"Batch": "Setup", "URL": "N/A", "Reason": f"Could not validate Streamrip config: {streamrip_settings_error}"}], [], [], log_path
    try:
        os.makedirs(os.path.dirname(os.path.abspath(os.path.expanduser(downloads_db_path))), exist_ok=True)
        os.makedirs(os.path.abspath(os.path.expanduser(failed_downloads_path)), exist_ok=True)
    except Exception as e:
        return 0, 0, [{"Batch": "Setup", "URL": "N/A", "Reason": f"Could not prepare streamrip database/failed directories: {e}"}], [], [], log_path

    success_count = 0
    total_urls = 0
    failures: List[dict] = []
    skipped: List[dict] = []
    successes: List[dict] = []
    batch_urls: List[tuple[str, List[str]]] = []
    for fname in batch_files:
        rel_path = os.path.join("exports", fname)
        _streamrip_debug(f"Loading batch file `{rel_path}`.")
        try:
            with open(rel_path, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip()]
        except Exception as e:
            failures.append({"Batch": fname, "URL": "N/A", "Reason": f"could not read batch file ({e})"})
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[{fname}] read error: {e}\n")
            continue

        if not urls:
            failures.append({"Batch": fname, "URL": "N/A", "Reason": "no URLs found"})
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[{fname}] no URLs found\n")
            continue

        total_urls += len(urls)
        batch_urls.append((fname, urls))
    _streamrip_debug(f"Prepared {len(batch_urls)} non-empty batch file(s), total_urls={total_urls}.")

    if status_callback:
        status_callback(0, total_urls, f"Preparing streamrip run for {total_urls} URL(s)...")

    processed_urls = 0
    for fname, urls in batch_urls:
        file_failed = False
        _streamrip_debug(f"Processing batch `{fname}` with {len(urls)} URL(s).")
        for url in urls:
            if status_callback:
                status_callback(
                    processed_urls,
                    total_urls,
                    f"Ripping {processed_urls + 1}/{total_urls}: {url}",
                )
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
                _streamrip_debug(
                    f"URL timed out after {streamrip_timeout_seconds}s: batch=`{fname}`, url=`{url}`."
                )
                with open(log_path, "a", encoding="utf-8") as log:
                    log.write(
                        f"[timeout] {datetime.now(timezone.utc).isoformat()} :: {' '.join(cmd)}\n\n"
                    )
                failures.append(
                    {"Batch": fname, "URL": url, "Reason": f"timed out after {streamrip_timeout_seconds}s"}
                )
                file_failed = True
                processed_urls += 1
                if status_callback:
                    status_callback(
                        processed_urls,
                        total_urls,
                        f"Timed out {processed_urls}/{total_urls}: {url}",
                    )
                if progress_callback:
                    progress_callback(log_path, _read_log_tail(log_path))
                continue

            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"$ {' '.join(cmd)}\n")
                log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n\n")
            if progress_callback:
                progress_callback(log_path, _read_log_tail(log_path))
                
            with open(log_path, "r", encoding="utf-8", errors="replace") as log_read:
                log_read.seek(log_offset_before)
                recent_output = log_read.read().lower()

            if result_code != 0:
                if "enter your qobuz email" in recent_output or "enter your qobuz password" in recent_output:
                    failures.append({"Batch": fname, "URL": url, "Reason": "Streamrip is not configured. Open 'Streamrip Setup'"})
                else:
                    failures.append({"Batch": fname, "URL": url, "Reason": f"exit code {result_code}"})
                file_failed = True
            else:
                has_skip_keywords = "already in the database" in recent_output or "skipping" in recent_output or "already downloaded" in recent_output
                has_download_keywords = "downloading" in recent_output or "saved to" in recent_output
                
                # If we have skip keywords but NO download keywords, it's a total skip
                if has_skip_keywords and not has_download_keywords:
                    skipped.append({"Batch": fname, "URL": url, "Reason": "Already downloaded/skipped"})
                else:
                    # Otherwise, if it finished with 0, we treat it as a success (even if partial)
                    successes.append({"Batch": fname, "URL": url, "Status": "Downloaded / Loaded"})
            processed_urls += 1
            if status_callback:
                if result_code == 0:
                    status_callback(
                        processed_urls,
                        total_urls,
                        f"Completed {processed_urls}/{total_urls}: {url}",
                    )
                else:
                    status_callback(
                        processed_urls,
                        total_urls,
                        f"Failed {processed_urls}/{total_urls}: {url}",
                    )

        if not file_failed:
            success_count += 1
            _streamrip_debug(f"Batch `{fname}` completed without URL failures.")

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(
            f"Streamrip run finished: {datetime.now(timezone.utc).isoformat()} "
            f"(batches_ok={success_count}, urls={total_urls}, failures={len(failures)})\n"
        )
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))
    if status_callback:
        if failures:
            status_callback(total_urls, total_urls, f"Finished with {len(failures)} error(s).")
        else:
            status_callback(total_urls, total_urls, "Finished successfully.")

    _streamrip_debug(
        f"run_streamrip_batches() finished: success_batches={success_count}, "
        f"total_urls={total_urls}, failures={len(failures)}, skipped={len(skipped)}, successes={len(successes)}."
    )
    return success_count, total_urls, failures, skipped, successes, log_path


def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def list_export_batch_files() -> List[str]:
    export_dir = os.path.abspath("exports")
    _streamrip_debug(f"Listing export batch files in `{export_dir}`.")
    if not os.path.isdir(export_dir):
        _streamrip_debug("Export directory missing; no batch files found.")
        return []
    files = sorted(
        f
        for f in os.listdir(export_dir)
        if f.startswith("qobuz_batch_") and f.endswith(".txt")
    )
    _streamrip_debug(f"Found {len(files)} export batch file(s).")
    return files


def export_qobuz_batches(valid_urls: List[str], max_links: int, rip_quality: int, rip_codec: str) -> tuple[List[str], int]:
    _streamrip_debug(
        f"export_qobuz_batches() called with {len(valid_urls)} URL(s), max_links={max_links}, "
        f"quality={rip_quality}, codec={rip_codec}."
    )
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
    _streamrip_debug(f"Wrote {len(batch_files)} streamrip batch file(s) to `{export_dir}`.")

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

    _streamrip_debug(
        f"Export artifacts generated: run scripts at `{bat_path}` and `{sh_path}` "
        f"for {total_batches} batch(es)."
    )
    return batch_files, total_batches
