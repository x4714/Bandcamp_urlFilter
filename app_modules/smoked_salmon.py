import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from app_modules.debug_logging import emit_debug

SALMON_SOURCE_OPTIONS = ["WEB", "CD", "VINYL", "SOUNDBOARD", "SACD", "DAT", "CASSETTE"]
SALMON_REQUIRED_TOOLS = ["flac", "sox", "lame", "mp3val", "curl", "git"]


def _salmon_debug(message: str) -> None:
    emit_debug("smoked-salmon", message)


def get_smoked_salmon_config_path() -> str:
    _salmon_debug("Resolving smoked-salmon config path.")
    if os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        resolved = os.path.join(local_appdata, "smoked-salmon", "config.toml")
        _salmon_debug(f"Using Windows smoked-salmon config path: `{resolved}`")
        return resolved
    if sys.platform == "darwin":
        resolved = os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "smoked-salmon",
            "config.toml",
        )
        _salmon_debug(f"Using macOS smoked-salmon config path: `{resolved}`")
        return resolved
    config_home = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    resolved = os.path.join(config_home, "smoked-salmon", "config.toml")
    _salmon_debug(f"Using Linux smoked-salmon config path: `{resolved}`")
    return resolved


def ensure_smoked_salmon_config_file(config_path: str) -> tuple[bool, str]:
    _salmon_debug(f"Ensuring smoked-salmon config exists at `{config_path}`.")
    if os.path.exists(config_path):
        _salmon_debug("smoked-salmon config already exists.")
        return True, ""

    template_path = find_smoked_salmon_default_config_template_path()
    if template_path:
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            shutil.copyfile(template_path, config_path)
            _salmon_debug(f"Copied template config from `{template_path}` to `{config_path}`.")
            _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(config_path)
            suffix = f" {dir_msg}" if dir_msg else ""
            return True, f"Created smoked-salmon config from `{template_path}` at `{config_path}`.{suffix}"
        except Exception as e:
            _salmon_debug(f"Could not create config from template: {e}")
            return False, f"Could not create smoked-salmon config: {e}"

    # Fallback: run salmon once to let it generate config.default.toml interactively,
    # then copy it to config.toml.
    boot_ok, boot_msg = bootstrap_smoked_salmon_default_config(config_path)
    if boot_ok and os.path.exists(config_path):
        _salmon_debug("Bootstrap created smoked-salmon config successfully.")
        return True, boot_msg
    _salmon_debug("Failed to create smoked-salmon config via template and bootstrap paths.")
    return False, (
        "Could not find smoked-salmon default template (`src/salmon/data/config.default.toml`) "
        "and could not auto-generate config via `salmon`."
    )


def read_smoked_salmon_config_text(config_path: str) -> str:
    _salmon_debug(f"Reading smoked-salmon config text from `{config_path}`.")
    if not os.path.exists(config_path):
        _salmon_debug("Config text read requested, but file does not exist.")
        return ""
    with open(config_path, "r", encoding="utf-8") as f:
        return f.read()


def save_smoked_salmon_config_text(config_path: str, text: str) -> tuple[bool, str]:
    _salmon_debug(f"Saving smoked-salmon config text to `{config_path}`.")
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
        _salmon_debug(f"Could not save smoked-salmon config: {e}")
        return False, f"Could not save smoked-salmon config: {e}"


def _upsert_toml_value(text: str, section_name: str, key: str, rendered_value: str) -> str:
    lines = text.splitlines(keepends=True)
    section_header = f"[{section_name}]"
    section_start = -1
    for idx, line in enumerate(lines):
        if line.strip() == section_header:
            section_start = idx
            break

    if section_start == -1:
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        return text + f"{section_header}\n{key} = {rendered_value}\n"

    section_end = len(lines)
    for idx in range(section_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_end = idx
            break

    key_prefix = f"{key} = "
    for idx in range(section_start + 1, section_end):
        stripped = lines[idx].lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            newline = "\n" if lines[idx].endswith("\n") else ""
            lines[idx] = f"{key_prefix}{rendered_value}{newline}"
            return "".join(lines)

    lines.insert(section_end, f"{key_prefix}{rendered_value}\n")
    return "".join(lines)


def apply_smoked_salmon_ai_review_settings(config_path: str, enabled: bool, api_key: str) -> tuple[bool, str]:
    _salmon_debug(
        f"Applying AI review settings in `{config_path}` (enabled={enabled}, api_key_present={bool(api_key)})."
    )
    current_text = read_smoked_salmon_config_text(config_path)
    if not current_text:
        _salmon_debug("AI review settings update failed: config text was empty/unreadable.")
        return False, f"Could not read smoked-salmon config at `{config_path}`."

    updated = _upsert_toml_value(
        current_text,
        "upload.ai_review",
        "enabled",
        "true" if enabled else "false",
    )
    if enabled:
        escaped_key = api_key.replace("\\", "\\\\").replace('"', '\\"')
        updated = _upsert_toml_value(
            updated,
            "upload.ai_review",
            "api_key",
            f'"{escaped_key}"',
        )

    if updated == current_text:
        _salmon_debug("AI review settings already matched config; no file write needed.")
        return True, "AI review settings already match config."
    _salmon_debug("AI review settings changed; writing updated config.")
    return save_smoked_salmon_config_text(config_path, updated)

def resolve_smoked_salmon_command() -> List[str]:
    _salmon_debug("Resolving smoked-salmon command.")
    salmon_bin = shutil.which("salmon")
    if salmon_bin:
        _salmon_debug(f"Using salmon binary from PATH: `{salmon_bin}`.")
        return [salmon_bin]

    uv_bin = resolve_uv_command()
    if uv_bin:
        probe = subprocess.run(
            [uv_bin, "tool", "run", "salmon", "--help"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            _salmon_debug(f"Using `uv tool run salmon` via `{uv_bin}`.")
            return [uv_bin, "tool", "run", "salmon"]
    _salmon_debug("Could not resolve smoked-salmon command.")
    return []


def resolve_uv_command() -> str:
    _salmon_debug("Resolving uv command.")
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
                _salmon_debug(f"Resolved uv command: `{normalized}`")
                return normalized
        except Exception:
            continue
    _salmon_debug("uv command not detected in PATH/common install locations.")
    return ""


def check_smoked_salmon_setup() -> dict:
    _salmon_debug("Checking smoked-salmon setup.")
    config_path = get_smoked_salmon_config_path()
    missing_tools = [tool for tool in SALMON_REQUIRED_TOOLS if not shutil.which(tool)]
    uv_bin = resolve_uv_command()
    salmon_cmd = resolve_smoked_salmon_command()

    result = {
        "config_path": config_path,
        "config_exists": os.path.exists(config_path),
        "has_uv": bool(uv_bin),
        "uv_command": uv_bin,
        "salmon_command": salmon_cmd,
        "has_salmon": bool(salmon_cmd),
        "missing_required_tools": missing_tools,
        "ready": bool(salmon_cmd) and not missing_tools,
    }
    _salmon_debug(
        f"Setup check complete. config_exists={result['config_exists']}, "
        f"has_salmon={result['has_salmon']}, missing_tools={len(missing_tools)}."
    )
    return result


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
    _salmon_debug("Searching for smoked-salmon default config template path.")
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
            _salmon_debug(f"Found smoked-salmon config template at `{normalized}`.")
            return normalized
    _salmon_debug("No smoked-salmon default config template found.")
    return ""


def bootstrap_smoked_salmon_default_config(config_path: str) -> tuple[bool, str]:
    _salmon_debug(f"Bootstrapping smoked-salmon default config at `{config_path}`.")
    salmon_cmd = resolve_smoked_salmon_command()
    if not salmon_cmd:
        _salmon_debug("Bootstrap aborted: smoked-salmon command not found.")
        return False, "smoked-salmon command not found."

    config_dir = os.path.dirname(os.path.abspath(config_path))
    default_config_path = os.path.join(config_dir, "config.default.toml")
    os.makedirs(config_dir, exist_ok=True)

    # If default already exists, use it.
    if os.path.exists(default_config_path) and not os.path.exists(config_path):
        shutil.copyfile(default_config_path, config_path)
        _salmon_debug("Bootstrap reused existing config.default.toml.")
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
            _salmon_debug(f"Bootstrap timed out after {timeout_seconds}s; process killed.")
    except Exception:
        _salmon_debug("Bootstrap failed to run smoked-salmon command.")
        return False, "Failed to run smoked-salmon bootstrap command."

    if os.path.exists(default_config_path) and not os.path.exists(config_path):
        try:
            shutil.copyfile(default_config_path, config_path)
            _salmon_debug("Bootstrap generated config.default.toml and copied config.toml.")
            _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(config_path)
            suffix = f" {dir_msg}" if dir_msg else ""
            return True, f"Generated `{default_config_path}` and created `{config_path}`.{suffix}"
        except Exception:
            _salmon_debug("Bootstrap generated default config but copy to config.toml failed.")
            return False, f"Generated `{default_config_path}` but failed to copy to `{config_path}`."

    if os.path.exists(config_path):
        _salmon_debug("Bootstrap detected config.toml created directly by smoked-salmon.")
        _ok_dir, dir_msg = ensure_smoked_salmon_directory_settings(config_path)
        suffix = f" {dir_msg}" if dir_msg else ""
        return True, f"smoked-salmon created `{config_path}`.{suffix}"

    _salmon_debug("Bootstrap completed without generating expected config files.")
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
        pacman_tools = [tool for tool in missing if tool != "mp3val"]
        if pacman_tools:
            commands.append(f"sudo pacman -S --needed {' '.join(pacman_tools)}")
        if "mp3val" in missing:
            commands.append("# mp3val is in AUR (not in official pacman repos)")
            commands.append("yay -S mp3val")
            commands.append("paru -S mp3val")
    else:
        platform_label = "Linux (Debian/Ubuntu)"
        commands.append("sudo apt update && sudo apt install -y sox flac mp3val curl lame git")

    return {"platform_label": platform_label, "commands": commands}


def ensure_smoked_salmon_directory_settings(config_path: str) -> tuple[bool, str]:
    _salmon_debug(f"Ensuring smoked-salmon directory settings in `{config_path}`.")
    target_path = os.path.abspath(os.path.expanduser(config_path))
    if not os.path.exists(target_path):
        _salmon_debug("Directory setting normalization skipped; config path does not exist.")
        return False, ""

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        _salmon_debug(f"Could not read config for directory normalization: {e}")
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
                _salmon_debug(
                    f"Could not create `{key}` at `{path}` and fallback `{fallback_path}` failed: {fallback_error}"
                )
                return False, (
                    f"Could not create `{key}` directory at `{path}`: {e}. "
                    f"Fallback failed at `{fallback_path}`: {fallback_error}"
                )
            resolved_paths[key] = fallback_path
            modified = True
            _salmon_debug(
                f"Directory `{key}` fallback applied. requested=`{path}`, fallback=`{fallback_path}`."
            )

    if modified:
        try:
            updated_text = _set_directory_key_value("".join(output_lines), "download_directory", resolved_paths["download_directory"])
            updated_text = _set_directory_key_value(updated_text, "dottorrents_dir", resolved_paths["dottorrents_dir"])
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(updated_text)
        except Exception as e:
            _salmon_debug(f"Failed writing normalized directory settings: {e}")
            return False, f"Could not write normalized directory settings: {e}"
        _salmon_debug("Directory settings updated in config file.")

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
                _salmon_debug(f"Writable smoked-salmon root detected: `{normalized}`.")
                return normalized
        except Exception:
            continue
    # Last-resort fallback (caller may still fail later on mkdir)
    fallback = os.path.abspath(os.path.join("exports", "smoked-salmon"))
    _salmon_debug(f"Using fallback smoked-salmon writable root: `{fallback}`.")
    return fallback


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
    _salmon_debug("Installing smoked-salmon with uv.")
    log_path = os.path.abspath(os.path.join("exports", "smoked_salmon_install_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    uv_bin = resolve_uv_command()
    if not uv_bin:
        _salmon_debug("uv missing; attempting uv installer before smoked-salmon install.")
        uv_ok, uv_msg, uv_log_path = install_uv_tool(progress_callback=progress_callback)
        if not uv_ok:
            _salmon_debug(f"uv install failed: {uv_msg}")
            return False, f"{uv_msg} (see: {uv_log_path})", log_path
        uv_bin = resolve_uv_command()
        if not uv_bin:
            _salmon_debug("uv install reported success but uv command still unresolved.")
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
        _salmon_debug(f"smoked-salmon install timed out after {timeout_seconds}s.")
        return False, f"Install timed out after {timeout_seconds}s.", log_path

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if result_code != 0:
        _salmon_debug(f"smoked-salmon install failed with exit code {result_code}.")
        return False, f"`uv tool install ...` failed with exit code {result_code}.", log_path

    check = check_smoked_salmon_setup()
    if check.get("has_salmon"):
        _salmon_debug("smoked-salmon install completed successfully and command is now detected.")
        return True, "smoked-salmon installed successfully.", log_path
    _salmon_debug("Install command completed but salmon command is still not detected.")
    return False, "Install command finished, but `salmon` is still not detected in PATH.", log_path


def install_uv_tool(
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[bool, str, str]:
    _salmon_debug("Installing uv tool.")
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
        _salmon_debug(f"uv install timed out after {timeout_seconds}s.")
        return False, f"uv install timed out after {timeout_seconds}s.", log_path

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if result_code != 0:
        _salmon_debug(f"uv install failed with exit code {result_code}.")
        return False, f"uv install failed with exit code {result_code}.", log_path

    detected_uv = resolve_uv_command()
    if detected_uv:
        _salmon_debug(f"uv install succeeded and detected binary `{detected_uv}`.")
        return True, f"uv installed successfully (`{detected_uv}`).", log_path
    _salmon_debug("uv install completed but uv command still unresolved.")
    return False, "uv install finished, but `uv` is still not detected in PATH/common locations.", log_path


def run_smoked_salmon_uploads(
    album_paths: List[str],
    source: str = "WEB",
    extra_args: str = "",
    lossy_master_choice: str = "",
    lossy_master_comment: str = "",
    custom_prompt_responses: Optional[Dict[str, str]] = None,
    fail_on_unhandled_prompt: bool = True,
    env_overrides: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[int, int, List[str], str]:
    _salmon_debug(
        f"run_smoked_salmon_uploads() called with {len(album_paths)} album path(s), "
        f"source={source}, extra_args_present={bool(extra_args.strip())}."
    )
    base_cmd = resolve_smoked_salmon_command()
    log_path = os.path.abspath(os.path.join("exports", "smoked_salmon_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    timeout_seconds = 3600
    source_arg = source.strip().upper() or "WEB"
    try:
        extra_tokens = shlex.split(extra_args) if extra_args.strip() else []
    except ValueError as e:
        _salmon_debug(f"Invalid extra CLI args for smoked-salmon upload run: {e}")
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
        _salmon_debug("Upload run aborted: smoked-salmon command not found.")
        return 0, 0, [
            "smoked-salmon command not found.",
            "Install with: uv tool install git+https://github.com/smokin-salmon/smoked-salmon",
        ], log_path

    attempted = 0
    success_count = 0
    failures: List[str] = []
    lossy_choice = (lossy_master_choice or "").strip().lower()
    if lossy_choice not in {"y", "n", "r", "a", "d"}:
        lossy_choice = ""
    lossy_comment_value = (lossy_master_comment or "").strip()
    merged_prompt_responses = dict(custom_prompt_responses or {})

    prompt_responses: Dict[str, str] = {
        "24bit detected. do you want to check whether might be upconverted?": "y\n",
        "possible upconverts detected. would you like to quit uploading?": "n\n",
        "log file crc does not match audio files. do you want to continue upload anyway?": "y\n",
        "do you want to sanitize this upload?": "y\n",
        "would you like to upload the torrent? (no to re-run metadata section)": "y\n",
        "would you like to check downconversion options?": "y\n",
        "select formats to convert": "*\n",
        "confirm selection?": "y\n",
        "are there any metadata fields you would like to edit?": "n\n",
        "would you like to auto-tag the files with the updated metadata?": "y\n",
        "would you like to rename the files?": "y\n",
        "would you like to replace the original folder name?": "y\n",
        "is the new folder name acceptable? ([n] to edit)": "y\n",
    }
    if lossy_choice:
        prompt_responses["is this release lossy mastered?"] = f"{lossy_choice}\n"
    if lossy_comment_value:
        prompt_responses["do you have a comment for the lossy approval report?"] = f"{lossy_comment_value}\n"
    for key, value in merged_prompt_responses.items():
        cleaned_key = str(key).strip().lower()
        if not cleaned_key:
            continue
        rendered_value = str(value)
        if not rendered_value.endswith("\n"):
            rendered_value += "\n"
        prompt_responses[cleaned_key] = rendered_value

    prompt_indicators = (
        "would you",
        "do you",
        "are you",
        "select ",
        "choose ",
        "enter ",
        "[y",
        "[n",
        "[a",
        "[d",
        "[r",
        "[c",
        "[*",
        "[0",
        "[1",
    )
    child_env = os.environ.copy()
    if env_overrides:
        for key, value in env_overrides.items():
            if not str(key).strip():
                continue
            child_env[str(key)] = str(value)

    for album_path in album_paths:
        target = os.path.abspath(os.path.expanduser(album_path.strip()))
        if not target:
            continue
        if not os.path.isdir(target):
            _salmon_debug(f"Album path missing for upload run: `{target}`.")
            failures.append(f"{target}: folder not found")
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[missing] {datetime.now(timezone.utc).isoformat()} :: {target}\n")
            continue

        attempted += 1
        _salmon_debug(f"Starting smoked-salmon upload for `{target}`.")
        cmd = [*base_cmd, "up", target, "-s", source_arg, *extra_tokens]
        log_offset_before = 0
        with open(log_path, "a", encoding="utf-8") as log:
            log_offset_before = log.tell()
            log.write(f"[start] {datetime.now(timezone.utc).isoformat()} :: {target}\n")
            log.write(f"$ {' '.join(cmd)}\n")
            log.flush()

        process = None
        try:
            prompt_positions: Dict[str, int] = {key: -1 for key in prompt_responses}
            log_read_position = 0
            prompt_scan_buffer = ""
            unhandled_prompt_line = ""
            unhandled_prompt_hit = False
            with open(log_path, "a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.PIPE,
                    text=True,
                    env=child_env,
                )
            if process.stdin is not None and not process.stdin.closed:
                try:
                    # Prime one default response for any immediate startup prompt.
                    process.stdin.write("\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
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
                    # Scan new log output and reply to known interactive prompts.
                    try:
                        with open(log_path, "r", encoding="utf-8") as log_read:
                            log_read.seek(log_read_position)
                            new_text = log_read.read()
                            log_read_position = log_read.tell()
                    except Exception:
                        new_text = ""
                    if new_text and process.stdin is not None and not process.stdin.closed:
                        prompt_scan_buffer += new_text
                        # Keep buffer bounded while preserving enough context for prompt strings.
                        prompt_scan_buffer = prompt_scan_buffer[-20000:]
                        combined_lower = prompt_scan_buffer.lower()
                        for prompt_text, response_text in prompt_responses.items():
                            latest_pos = combined_lower.rfind(prompt_text)
                            if latest_pos > prompt_positions.get(prompt_text, -1):
                                try:
                                    process.stdin.write(response_text)
                                    process.stdin.flush()
                                    prompt_positions[prompt_text] = latest_pos
                                    with open(log_path, "a", encoding="utf-8") as log:
                                        rendered = response_text.rstrip("\n")
                                        if "lossy approval report" in prompt_text and rendered:
                                            rendered = "<provided in UI>"
                                        log.write(
                                            f"[auto-input] {prompt_text} -> "
                                            f"{rendered if rendered else '<default>'}\n"
                                        )
                                except (BrokenPipeError, OSError):
                                    pass
                        if fail_on_unhandled_prompt:
                            for raw_line in prompt_scan_buffer.splitlines()[-30:]:
                                line = raw_line.strip()
                                lower_line = line.lower()
                                if not line:
                                    continue
                                if any(prompt_text in lower_line for prompt_text in prompt_responses):
                                    continue
                                if ("?" in lower_line) or any(ind in lower_line for ind in prompt_indicators):
                                    unhandled_prompt_line = line
                                    break
                        if fail_on_unhandled_prompt and unhandled_prompt_line:
                            if process is not None:
                                process.kill()
                                process.wait()
                            _salmon_debug(
                                f"Upload aborted due to unhandled prompt for `{target}`: "
                                f"`{unhandled_prompt_line}`."
                            )
                            with open(log_path, "a", encoding="utf-8") as log:
                                log.write(
                                    f"[unhandled-prompt] {datetime.now(timezone.utc).isoformat()} :: "
                                    f"{unhandled_prompt_line}\n"
                                )
                            failures.append(
                                f"{target}: unhandled prompt detected -> `{unhandled_prompt_line}`. "
                                "Add a response rule in Smoked Salmon Settings."
                            )
                            unhandled_prompt_hit = True
                            result_code = 999
                            break
                    if progress_callback:
                        progress_callback(log_path, _read_log_tail(log_path))
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                process.wait()
            _salmon_debug(f"Upload timed out after {timeout_seconds}s for `{target}`.")
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

        recent_output = ""
        try:
            with open(log_path, "r", encoding="utf-8") as log_read:
                log_read.seek(log_offset_before)
                recent_output = log_read.read().lower()
        except Exception:
            recent_output = ""

        aborted_upload = "aborting upload" in recent_output
        if unhandled_prompt_hit:
            pass
        elif result_code == 0 and not aborted_upload:
            success_count += 1
            _salmon_debug(f"Upload succeeded for `{target}`.")
        else:
            if aborted_upload:
                _salmon_debug(f"Upload aborted by smoked-salmon interactive prompt for `{target}`.")
                failures.append(
                    f"{target}: upload aborted by smoked-salmon prompt "
                    "(try setting additional args to disable interactive checks)."
                )
            else:
                _salmon_debug(f"Upload failed with exit code {result_code} for `{target}`.")
                failures.append(f"{target}: exit code {result_code}")

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(
            f"Smoked-salmon run finished: {datetime.now(timezone.utc).isoformat()} "
            f"(attempted={attempted}, succeeded={success_count}, failures={len(failures)})\n"
        )
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    _salmon_debug(
        f"run_smoked_salmon_uploads() finished: attempted={attempted}, "
        f"succeeded={success_count}, failures={len(failures)}."
    )
    return success_count, attempted, failures, log_path


def run_smoked_salmon_command(
    command: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[bool, str, str]:
    _salmon_debug(f"run_smoked_salmon_command() called with command=`{command}`.")
    base_cmd = resolve_smoked_salmon_command()
    log_path = os.path.abspath(os.path.join("exports", "smoked_salmon_cmd_last.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    command = command.strip().lower()
    if command not in {"health", "checkconf", "migrate"}:
        _salmon_debug(f"Unsupported smoked-salmon command requested: `{command}`.")
        return False, f"Unsupported command: {command}", log_path

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"Smoked-salmon command started: {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"Command: {command}\n")
        log.write(f"Base command: {' '.join(base_cmd) if base_cmd else 'NOT FOUND'}\n\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if not base_cmd:
        _salmon_debug("Cannot run smoked-salmon command; binary not resolved.")
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
        _salmon_debug(f"`salmon {command}` timed out after {timeout_seconds}s.")
        return False, f"`salmon {command}` timed out after {timeout_seconds}s.", log_path

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[exit {result_code}] {datetime.now(timezone.utc).isoformat()}\n")
    if progress_callback:
        progress_callback(log_path, _read_log_tail(log_path))

    if result_code == 0:
        _salmon_debug(f"`salmon {command}` completed successfully.")
        return True, f"`salmon {command}` completed successfully.", log_path
    _salmon_debug(f"`salmon {command}` failed with exit code {result_code}.")
    return False, f"`salmon {command}` failed with exit code {result_code}.", log_path



def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""
