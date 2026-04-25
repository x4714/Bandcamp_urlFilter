import os
import re
from typing import List

from app_modules.debug_logging import emit_debug


def _salmon_debug(message: str) -> None:
    emit_debug("smoked-salmon", message)


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
