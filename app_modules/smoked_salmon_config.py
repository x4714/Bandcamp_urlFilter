from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
import tomllib
from typing import Any, List

from app_modules.debug_logging import emit_debug
from app_modules.smoked_salmon_fs import ensure_smoked_salmon_directory_settings

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
        "Could not find smoked-salmon default template (`salmon/data/config.default.toml`) "
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


def _ensure_toml_section(config_data: dict[str, Any], section_name: str) -> dict[str, Any]:
    current: dict[str, Any] = config_data
    for segment in section_name.split("."):
        existing = current.get(segment)
        if not isinstance(existing, dict):
            existing = {}
            current[segment] = existing
        current = existing
    return current


def _dump_toml(config_data: dict[str, Any]) -> tuple[bool, str]:
    try:
        import tomli_w
    except ModuleNotFoundError:
        return False, "Could not save smoked-salmon config: missing dependency `tomli-w`."

    try:
        return True, tomli_w.dumps(config_data)
    except Exception as e:
        return False, f"Could not serialize smoked-salmon config TOML: {e}"


def apply_smoked_salmon_ai_review_settings(config_path: str, enabled: bool, api_key: str) -> tuple[bool, str]:
    _salmon_debug(
        f"Applying AI review settings in `{config_path}` (enabled={enabled}, api_key_present={bool(api_key)})."
    )
    current_text = read_smoked_salmon_config_text(config_path)
    if not current_text:
        _salmon_debug("AI review settings update failed: config text was empty/unreadable.")
        return False, f"Could not read smoked-salmon config at `{config_path}`."

    try:
        parsed = tomllib.loads(current_text)
    except tomllib.TOMLDecodeError as e:
        _salmon_debug(f"AI review settings update failed: invalid TOML: {e}")
        return False, f"Could not parse smoked-salmon config TOML: {e}"
    if not isinstance(parsed, dict):
        _salmon_debug("AI review settings update failed: parsed TOML root was not a table.")
        return False, "Could not parse smoked-salmon config TOML: root table is invalid."

    original = copy.deepcopy(parsed)
    ai_review_table = _ensure_toml_section(parsed, "upload.ai_review")
    ai_review_table["enabled"] = bool(enabled)
    if enabled:
        ai_review_table["api_key"] = str(api_key)

    if parsed == original:
        _salmon_debug("AI review settings already matched config; no file write needed.")
        return True, "AI review settings already match config."

    dump_ok, updated = _dump_toml(parsed)
    if not dump_ok:
        _salmon_debug(updated)
        return False, updated
    _salmon_debug("AI review settings changed; writing updated config.")
    return save_smoked_salmon_config_text(config_path, updated)


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
    candidates = [
        os.path.abspath(os.path.join("salmon", "data", "config.default.toml")),
        os.path.abspath(os.path.join("src", "salmon", "data", "config.default.toml")),
        os.path.abspath(os.path.join(".smoked-salmon", "src", "salmon", "data", "config.default.toml")),
        os.path.abspath(os.path.join(".smoked-salmon", "salmon", "data", "config.default.toml")),
        os.path.abspath(
            os.path.join(os.path.expanduser("~"), ".smoked-salmon", "src", "salmon", "data", "config.default.toml")
        ),
        os.path.abspath(os.path.join(os.path.expanduser("~"), ".smoked-salmon", "salmon", "data", "config.default.toml")),
    ]

    # Try deriving from the installed salmon executable path.
    salmon_bin = shutil.which("salmon")
    if salmon_bin:
        salmon_dir = os.path.dirname(os.path.abspath(salmon_bin))
        candidates.extend(
            [
                os.path.abspath(os.path.join(salmon_dir, "..", "src", "salmon", "data", "config.default.toml")),
                os.path.abspath(os.path.join(salmon_dir, "..", "salmon", "data", "config.default.toml")),
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
    from app_modules.smoked_salmon_upload import resolve_smoked_salmon_command

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
