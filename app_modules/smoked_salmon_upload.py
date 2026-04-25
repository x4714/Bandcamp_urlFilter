import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from app_modules.debug_logging import emit_debug

SALMON_SOURCE_OPTIONS = ["WEB", "CD", "VINYL", "SOUNDBOARD", "SACD", "DAT", "CASSETTE"]
SALMON_LOG_TAIL_CHARS = 6000
SALMON_PROMPT_SCAN_BUFFER_CHARS = 20000
SALMON_UPLOAD_TIMEOUT_SECONDS = 3600
SALMON_UV_INSTALL_TIMEOUT_SECONDS = 900
DEFAULT_SMOKED_SALMON_PROMPT_RESPONSES: Dict[str, str] = {
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


def _salmon_debug(message: str) -> None:
    emit_debug("smoked-salmon", message)


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
    from app_modules.smoked_salmon_config import SALMON_REQUIRED_TOOLS, get_smoked_salmon_config_path

    _salmon_debug("Checking smoked-salmon setup.")
    config_path = get_smoked_salmon_config_path()
    missing_tools = [tool for tool in SALMON_REQUIRED_TOOLS if not shutil.which(tool)]
    uv_bin = resolve_uv_command()
    salmon_cmd = resolve_smoked_salmon_command()
    command_mode = ""
    if salmon_cmd[:3] == [uv_bin, "tool", "run"] if uv_bin else False:
        command_mode = "uv"
    elif salmon_cmd:
        command_mode = "path"

    result = {
        "config_path": config_path,
        "config_exists": os.path.exists(config_path),
        "has_uv": bool(uv_bin),
        "uv_command": uv_bin,
        "salmon_command_mode": command_mode,
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
    timeout_seconds = SALMON_UV_INSTALL_TIMEOUT_SECONDS

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
    timeout_seconds = SALMON_UPLOAD_TIMEOUT_SECONDS
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

    prompt_responses: Dict[str, str] = dict(DEFAULT_SMOKED_SALMON_PROMPT_RESPONSES)
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
                        prompt_scan_buffer = prompt_scan_buffer[-SALMON_PROMPT_SCAN_BUFFER_CHARS:]
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


def _read_log_tail(log_path: str, max_chars: int = SALMON_LOG_TAIL_CHARS) -> str:
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""
