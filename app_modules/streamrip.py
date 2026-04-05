import json
import os
import re
import shlex
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
SALMON_SOURCE_OPTIONS = ["WEB", "CD", "VINYL", "SOUNDBOARD", "SACD", "DAT", "CASSETTE"]
SALMON_REQUIRED_TOOLS = ["flac", "sox", "lame", "mp3val", "curl", "git"]
QOBUZ_URL_REGEX = re.compile(r"https?://(?:www\.|play\.)?qobuz\.com/[^\s\"'<>]+", re.IGNORECASE)


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


def get_smoked_salmon_config_path() -> str:
    if os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(local_appdata, "smoked-salmon", "config.toml")
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "smoked-salmon",
            "config.toml",
        )
    config_home = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(config_home, "smoked-salmon", "config.toml")


def ensure_smoked_salmon_config_file(config_path: str) -> tuple[bool, str]:
    if os.path.exists(config_path):
        return True, ""

    template_path = find_smoked_salmon_default_config_template_path()
    if template_path:
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            shutil.copyfile(template_path, config_path)
            _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(config_path)
            suffix = f" {dir_msg}" if dir_msg else ""
            return True, f"Created smoked-salmon config from `{template_path}` at `{config_path}`.{suffix}"
        except Exception as e:
            return False, f"Could not create smoked-salmon config: {e}"

    # Fallback: run salmon once to let it generate config.default.toml interactively,
    # then copy it to config.toml.
    boot_ok, boot_msg = bootstrap_smoked_salmon_default_config(config_path)
    if boot_ok and os.path.exists(config_path):
        return True, boot_msg
    return False, (
        "Could not find smoked-salmon default template (`src/salmon/data/config.default.toml`) "
        "and could not auto-generate config via `salmon`."
    )


def read_smoked_salmon_config_text(config_path: str) -> str:
    if not os.path.exists(config_path):
        return ""
    with open(config_path, "r", encoding="utf-8") as f:
        return f.read()


def save_smoked_salmon_config_text(config_path: str, text: str) -> tuple[bool, str]:
    try:
        target_path = os.path.abspath(os.path.expanduser(config_path))
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(text)
        _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(target_path)
        dir_suffix = f" {dir_msg}" if dir_msg else ""
        return (
            True,
            f"smoked-salmon config saved: {target_path} ({len(text.encode('utf-8'))} bytes).{dir_suffix}",
        )
    except Exception as e:
        return False, f"Could not save smoked-salmon config: {e}"


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


def resolve_smoked_salmon_command() -> List[str]:
    salmon_bin = shutil.which("salmon")
    if salmon_bin:
        return [salmon_bin]

    uv_bin = resolve_uv_command()
    if uv_bin:
        probe = subprocess.run(
            [uv_bin, "tool", "run", "salmon", "--help"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return [uv_bin, "tool", "run", "salmon"]
    return []


def resolve_uv_command() -> str:
    candidates = []
    direct = shutil.which("uv")
    if direct:
        candidates.append(direct)

    candidates.extend(
        [
            os.path.expanduser("~/.local/bin/uv"),
            os.path.expanduser("~/.cargo/bin/uv"),
            "/opt/homebrew/bin/uv",
            "/usr/local/bin/uv",
            "/usr/bin/uv",
        ]
    )

    if os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA", "")
        if local_appdata:
            candidates.append(os.path.join(local_appdata, "Programs", "uv", "bin", "uv.exe"))

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(os.path.expanduser(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if not os.path.isfile(normalized):
            continue
        if os.name != "nt" and not os.access(normalized, os.X_OK):
            continue
        try:
            probe = subprocess.run(
                [normalized, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.returncode == 0:
                return normalized
        except Exception:
            continue
    return ""


def check_smoked_salmon_setup() -> dict:
    config_path = get_smoked_salmon_config_path()
    missing_tools = [tool for tool in SALMON_REQUIRED_TOOLS if not shutil.which(tool)]
    uv_bin = resolve_uv_command()
    salmon_cmd = resolve_smoked_salmon_command()

    return {
        "config_path": config_path,
        "config_exists": os.path.exists(config_path),
        "has_uv": bool(uv_bin),
        "uv_command": uv_bin,
        "salmon_command": salmon_cmd,
        "has_salmon": bool(salmon_cmd),
        "missing_required_tools": missing_tools,
        "ready": bool(salmon_cmd) and not missing_tools,
    }


def _detect_linux_distro() -> str:
    os_release = "/etc/os-release"
    if not os.path.exists(os_release):
        return ""
    try:
        with open(os_release, "r", encoding="utf-8") as f:
            data = f.read().lower()
    except Exception:
        return ""

    if "id=arch" in data or "id_like=arch" in data:
        return "arch"
    if "id=debian" in data or "id=ubuntu" in data or "id_like=debian" in data:
        return "debian"
    return ""


def find_smoked_salmon_default_config_template_path() -> str:
    # Prefer canonical source-tree location requested by user:
    # src/salmon/data/config.default.toml
    candidates = [
        os.path.abspath(os.path.join("src", "salmon", "data", "config.default.toml")),
        os.path.abspath(os.path.join(".smoked-salmon", "src", "salmon", "data", "config.default.toml")),
        os.path.abspath(os.path.join(os.path.expanduser("~"), ".smoked-salmon", "src", "salmon", "data", "config.default.toml")),
    ]

    # Try deriving from the installed salmon executable path.
    salmon_bin = shutil.which("salmon")
    if salmon_bin:
        salmon_dir = os.path.dirname(os.path.abspath(salmon_bin))
        candidates.extend(
            [
                os.path.abspath(os.path.join(salmon_dir, "..", "src", "salmon", "data", "config.default.toml")),
                os.path.abspath(os.path.join(salmon_dir, "..", "lib", "python3.12", "site-packages", "salmon", "data", "config.default.toml")),
                os.path.abspath(os.path.join(salmon_dir, "..", "lib", "python3.11", "site-packages", "salmon", "data", "config.default.toml")),
                os.path.abspath(os.path.join(salmon_dir, "..", "lib", "python3.10", "site-packages", "salmon", "data", "config.default.toml")),
            ]
        )

    seen = set()
    for path in candidates:
        normalized = os.path.abspath(os.path.expanduser(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(normalized):
            return normalized
    return ""


def bootstrap_smoked_salmon_default_config(config_path: str) -> tuple[bool, str]:
    salmon_cmd = resolve_smoked_salmon_command()
    if not salmon_cmd:
        return False, "smoked-salmon command not found."

    config_dir = os.path.dirname(os.path.abspath(config_path))
    default_config_path = os.path.join(config_dir, "config.default.toml")
    os.makedirs(config_dir, exist_ok=True)

    # If default already exists, use it.
    if os.path.exists(default_config_path) and not os.path.exists(config_path):
        shutil.copyfile(default_config_path, config_path)
        _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(config_path)
        suffix = f" {dir_msg}" if dir_msg else ""
        return True, f"Created `{config_path}` from existing `{default_config_path}`.{suffix}"

    timeout_seconds = 30
    process = None
    try:
        process = subprocess.Popen(
            salmon_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.PIPE,
            text=True,
        )
        try:
            process.communicate(input="y\n", timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except Exception:
        return False, "Failed to run smoked-salmon bootstrap command."

    if os.path.exists(default_config_path) and not os.path.exists(config_path):
        try:
            shutil.copyfile(default_config_path, config_path)
            _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(config_path)
            suffix = f" {dir_msg}" if dir_msg else ""
            return True, f"Generated `{default_config_path}` and created `{config_path}`.{suffix}"
        except Exception:
            return False, f"Generated `{default_config_path}` but failed to copy to `{config_path}`."

    if os.path.exists(config_path):
        _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(config_path)
        suffix = f" {dir_msg}" if dir_msg else ""
        return True, f"smoked-salmon created `{config_path}`.{suffix}"

    return False, "smoked-salmon did not generate config files."


def get_missing_tool_install_hints(missing_tools: List[str]) -> dict:
    missing = [tool for tool in SALMON_REQUIRED_TOOLS if tool in set(missing_tools)]
    if not missing:
        return {"platform_label": "", "commands": []}

    platform_label = ""
    commands: List[str] = []

    if os.name == "nt":
        platform_label = "Windows"
        commands.append("winget install -e ChrisBagwell.SoX Xiph.FLAC LAME.LAME ring0.MP3val.WF")
        if "curl" in missing:
            commands.append("winget install -e cURL.cURL")
        if "git" in missing:
            commands.append("winget install -e Git.Git")
        return {"platform_label": platform_label, "commands": commands}

    if sys.platform == "darwin":
        platform_label = "macOS"
        commands.append('/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
        commands.append("brew install sox flac mp3val curl lame git")
        return {"platform_label": platform_label, "commands": commands}

    distro = _detect_linux_distro()
    if distro == "arch":
        platform_label = "Linux (Arch)"
        commands.append("sudo pacman -S --needed sox flac mp3val curl lame git")
    else:
        platform_label = "Linux (Debian/Ubuntu)"
        commands.append("sudo apt update && sudo apt install -y sox flac mp3val curl lame git")

    return {"platform_label": platform_label, "commands": commands}


def ensure_smoked_salmon_directory_settings(config_path: str) -> tuple[bool, str]:
    target_path = os.path.abspath(os.path.expanduser(config_path))
    if not os.path.exists(target_path):
        return False, ""

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        return False, f"Could not read config to normalize directories: {e}"

    home_root = _get_writable_smoked_salmon_root(config_path)
    default_download = os.path.join(home_root, ".music")
    default_torrents = os.path.join(home_root, ".torrents")

    in_directory_section = False
    modified = False
    resolved_paths: dict[str, str] = {}
    output_lines: List[str] = []
    key_pattern = re.compile(r'^(\s*)(download_directory|dottorrents_dir)\s*=\s*([\'"])(.*?)\3(\s*(#.*)?)$')

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_directory_section = stripped == "[directory]"

        if in_directory_section:
            match = key_pattern.match(line.rstrip("\n"))
            if match:
                indent, key, quote, value, suffix, _comment = match.groups()
                raw_value = (value or "").strip()
                fallback_value = default_download if key == "download_directory" else default_torrents

                needs_default = (
                    not raw_value
                    or raw_value.lower().startswith("path to")
                    or raw_value.startswith("/path/to/")
                )
                if needs_default:
                    resolved = fallback_value
                else:
                    expanded = os.path.expanduser(raw_value)
                    resolved = expanded if os.path.isabs(expanded) else os.path.join(home_root, expanded)
                    resolved = os.path.abspath(resolved)

                resolved_paths[key] = resolved
                if raw_value != resolved:
                    modified = True
                output_lines.append(f"{indent}{key} = {quote}{resolved}{quote}{suffix}\n")
                continue

        output_lines.append(line)

    writable_root = _get_writable_smoked_salmon_root(config_path)
    fallback_by_key = {
        "download_directory": os.path.join(writable_root, ".music"),
        "dottorrents_dir": os.path.join(writable_root, ".torrents"),
    }

    for key, fallback in {
        "download_directory": default_download,
        "dottorrents_dir": default_torrents,
    }.items():
        path = resolved_paths.get(key, fallback)
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            fallback_path = fallback_by_key[key]
            try:
                os.makedirs(fallback_path, exist_ok=True)
            except Exception as fallback_error:
                return False, (
                    f"Could not create `{key}` directory at `{path}`: {e}. "
                    f"Fallback failed at `{fallback_path}`: {fallback_error}"
                )
            resolved_paths[key] = fallback_path
            modified = True

    if modified:
        try:
            updated_text = _set_directory_key_value("".join(output_lines), "download_directory", resolved_paths["download_directory"])
            updated_text = _set_directory_key_value(updated_text, "dottorrents_dir", resolved_paths["dottorrents_dir"])
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(updated_text)
        except Exception as e:
            return False, f"Could not write normalized directory settings: {e}"

    return (
        True,
        f"Directory settings ensured: download_directory=`{resolved_paths.get('download_directory', default_download)}`, "
        f"dottorrents_dir=`{resolved_paths.get('dottorrents_dir', default_torrents)}`.",
    )


def _get_writable_smoked_salmon_root(config_path: str) -> str:
    candidates = [
        os.path.join(os.path.expanduser("~"), ".smoked-salmon"),
        os.path.dirname(os.path.abspath(os.path.expanduser(config_path))),
        os.path.abspath(os.path.join("exports", "smoked-salmon")),
    ]
    seen = set()
    for candidate in candidates:
        normalized = os.path.abspath(os.path.expanduser(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            os.makedirs(normalized, exist_ok=True)
            if _is_directory_writable(normalized):
                return normalized
        except Exception:
            continue
    # Last-resort fallback (caller may still fail later on mkdir)
    return os.path.abspath(os.path.join("exports", "smoked-salmon"))


def _is_directory_writable(path: str) -> bool:
    probe_dir = os.path.join(path, ".salmon_write_probe")
    try:
        os.makedirs(probe_dir, exist_ok=True)
        probe_file = os.path.join(probe_dir, ".probe")
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
        os.rmdir(probe_dir)
        return True
    except Exception:
        return False


def _set_directory_key_value(config_text: str, key: str, value: str) -> str:
    lines = config_text.splitlines(keepends=True)
    in_directory_section = False
    pattern = re.compile(rf'^(\s*){re.escape(key)}\s*=\s*([\'"])(.*?)\2(\s*(#.*)?)$')
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_directory_section = stripped == "[directory]"
            continue
        if not in_directory_section:
            continue
        match = pattern.match(line.rstrip("\n"))
        if not match:
            continue
        indent, quote, _old, suffix, _comment = match.groups()
        lines[idx] = f"{indent}{key} = {quote}{value}{quote}{suffix}\n"
        break
    return "".join(lines)


def install_smoked_salmon_with_uv(
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[bool, str, str]:
    log_path = os.path.abspath(os.path.join("exports", "smoked_salmon_install_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    uv_bin = resolve_uv_command()
    if not uv_bin:
        uv_ok, uv_msg, uv_log_path = install_uv_tool(progress_callback=progress_callback)
        if not uv_ok:
            return False, f"{uv_msg} (see: {uv_log_path})", log_path
        uv_bin = resolve_uv_command()
        if not uv_bin:
            return False, "uv install reported success, but `uv` is still not detected.", log_path

    cmd = [uv_bin, "tool", "install", "git+https://github.com/smokin-salmon/smoked-salmon"]
    timeout_seconds = 1200

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"Smoked-salmon install started: {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"$ {' '.join(cmd)}\n\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

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
            remaining = timeout_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout_seconds)
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
            log.write(f"[timeout] {datetime.now(timezone.utc).isoformat()}\n")
        if progress_callback:
            progress_callback(log_path, _read_log_tail(log_path))
        return False, f"Install timed out after {timeout_seconds}s.", log_path

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if result_code != 0:
        return False, f"`uv tool install ...` failed with exit code {result_code}.", log_path

    check = check_smoked_salmon_setup()
    if check.get("has_salmon"):
        return True, "smoked-salmon installed successfully.", log_path
    return False, "Install command finished, but `salmon` is still not detected in PATH.", log_path


def install_uv_tool(
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[bool, str, str]:
    log_path = os.path.abspath(os.path.join("exports", "uv_install_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    timeout_seconds = 900

    if os.name == "nt":
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "ByPass",
            "-c",
            "irm https://astral.sh/uv/install.ps1 | iex",
        ]
    else:
        cmd = ["bash", "-lc", "curl -LsSf https://astral.sh/uv/install.sh | sh"]

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"uv install started: {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"$ {' '.join(cmd)}\n\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

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
            remaining = timeout_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout_seconds)
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
            log.write(f"[timeout] {datetime.now(timezone.utc).isoformat()}\n")
        if progress_callback:
            progress_callback(log_path, _read_log_tail(log_path))
        return False, f"uv install timed out after {timeout_seconds}s.", log_path

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if result_code != 0:
        return False, f"uv install failed with exit code {result_code}.", log_path

    detected_uv = resolve_uv_command()
    if detected_uv:
        return True, f"uv installed successfully (`{detected_uv}`).", log_path
    return False, "uv install finished, but `uv` is still not detected in PATH/common locations.", log_path


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


def run_smoked_salmon_uploads(
    album_paths: List[str],
    source: str = "WEB",
    extra_args: str = "",
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[int, int, List[str], str]:
    base_cmd = resolve_smoked_salmon_command()
    log_path = os.path.abspath(os.path.join("exports", "smoked_salmon_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    timeout_seconds = 3600
    source_arg = source.strip().upper() or "WEB"
    try:
        extra_tokens = shlex.split(extra_args) if extra_args.strip() else []
    except ValueError as e:
        return 0, 0, [f"Invalid additional CLI args: {e}"], log_path

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"Smoked-salmon run started: {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"Interpreter: {sys.executable}\n")
        log.write(f"Base command: {' '.join(base_cmd) if base_cmd else 'NOT FOUND'}\n")
        log.write(f"Source: {source_arg}\n")
        log.write(f"Extra args: {' '.join(extra_tokens) if extra_tokens else '(none)'}\n\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if not base_cmd:
        return 0, 0, [
            "smoked-salmon command not found.",
            "Install with: uv tool install git+https://github.com/smokin-salmon/smoked-salmon",
        ], log_path

    attempted = 0
    success_count = 0
    failures: List[str] = []

    for album_path in album_paths:
        target = os.path.abspath(os.path.expanduser(album_path.strip()))
        if not target:
            continue
        if not os.path.isdir(target):
            failures.append(f"{target}: folder not found")
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[missing] {datetime.now(timezone.utc).isoformat()} :: {target}\n")
            continue

        attempted += 1
        cmd = [*base_cmd, "up", target, "-s", source_arg, *extra_tokens]
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"[start] {datetime.now(timezone.utc).isoformat()} :: {target}\n")
            log.write(f"$ {' '.join(cmd)}\n")
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
                remaining = timeout_seconds - (time.monotonic() - started_at)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd, timeout_seconds)
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
            failures.append(f"{target}: timed out after {timeout_seconds}s")
            if progress_callback:
                progress_callback(log_path, _read_log_tail(log_path))
            continue

        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n\n")
        if progress_callback:
            progress_callback(log_path, _read_log_tail(log_path))

        if result_code == 0:
            success_count += 1
        else:
            failures.append(f"{target}: exit code {result_code}")

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(
            f"Smoked-salmon run finished: {datetime.now(timezone.utc).isoformat()} "
            f"(attempted={attempted}, succeeded={success_count}, failures={len(failures)})\n"
        )
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    return success_count, attempted, failures, log_path


def run_smoked_salmon_command(
    command: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[bool, str, str]:
    base_cmd = resolve_smoked_salmon_command()
    log_path = os.path.abspath(os.path.join("exports", "smoked_salmon_cmd_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    command = command.strip().lower()
    if command not in {"health", "checkconf", "migrate"}:
        return False, f"Unsupported command: {command}", log_path

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"Smoked-salmon command started: {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"Command: {command}\n")
        log.write(f"Base command: {' '.join(base_cmd) if base_cmd else 'NOT FOUND'}\n\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if not base_cmd:
        return False, "smoked-salmon command not found.", log_path

    cmd = [*base_cmd, command]
    process = None
    timeout_seconds = 600
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"$ {' '.join(cmd)}\n")
            log.flush()
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                text=True,
            )
        started_at = time.monotonic()
        while True:
            remaining = timeout_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout_seconds)
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
            log.write(f"[timeout] {datetime.now(timezone.utc).isoformat()}\n")
        if progress_callback:
            progress_callback(log_path, _read_log_tail(log_path))
        return False, f"`salmon {command}` timed out after {timeout_seconds}s.", log_path

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if result_code == 0:
        return True, f"`salmon {command}` completed successfully.", log_path
    return False, f"`salmon {command}` failed with exit code {result_code}.", log_path


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
