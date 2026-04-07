from io import StringIO
import os
import re
import sys
from datetime import datetime, timezone

import streamlit as st

from app_modules.debug_logging import emit_debug
from app_modules.smoked_salmon import (
    SALMON_SOURCE_OPTIONS,
    apply_smoked_salmon_ai_review_settings,
    check_smoked_salmon_setup,
    ensure_smoked_salmon_config_file,
    get_missing_tool_install_hints,
    get_smoked_salmon_config_path,
    install_smoked_salmon_with_uv,
    read_smoked_salmon_config_text,
    run_smoked_salmon_command,
    run_smoked_salmon_uploads,
    save_smoked_salmon_config_text,
)


def _ui_salmon_debug(message: str) -> None:
    emit_debug("ui smoked-salmon", message)


def _read_text_upload(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    return uploaded_file.getvalue().decode("utf-8", errors="ignore")


def _read_log_tail(log_path: str, max_chars: int = 6000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[-max_chars:]
    except Exception:
        return ""


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    matches = re.findall(r"https?://[^\s<>()\"']+", text, flags=re.IGNORECASE)
    seen = set()
    urls: list[str] = []
    for url in matches:
        clean = url.rstrip("),.;]}>")
        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls


def _extract_spectral_urls(text: str) -> list[str]:
    spectral_keywords = ("spectral", "spectrals", "lossy", "127.0.0.1", "localhost")
    image_suffixes = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
    urls = _extract_urls(text)
    selected: list[str] = []
    seen = set()
    for url in urls:
        lowered = url.lower()
        if any(k in lowered for k in spectral_keywords) or lowered.endswith(image_suffixes):
            if url not in seen:
                seen.add(url)
                selected.append(url)
    return selected


def _parse_prompt_rules(raw_text: str) -> tuple[dict[str, str], list[str]]:
    rules: dict[str, str] = {}
    errors: list[str] = []
    if not raw_text.strip():
        return rules, errors

    for idx, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" not in line:
            errors.append(f"Line {idx}: expected `prompt substring => answer`")
            continue
        prompt_text, answer_text = line.split("=>", 1)
        prompt_key = prompt_text.strip().lower()
        answer_value = answer_text.strip()
        if not prompt_key:
            errors.append(f"Line {idx}: prompt substring is empty")
            continue
        rules[prompt_key] = answer_value
    return rules, errors


def _collect_album_paths(single_path: str, multi_paths_text: str, uploaded_paths_file) -> list[str]:
    candidates = []
    if single_path.strip():
        candidates.append(single_path.strip())

    if multi_paths_text.strip():
        candidates.extend([line.strip() for line in StringIO(multi_paths_text).readlines() if line.strip()])

    if uploaded_paths_file is not None:
        file_text = _read_text_upload(uploaded_paths_file)
        candidates.extend([line.strip() for line in StringIO(file_text).readlines() if line.strip()])

    seen = set()
    unique_paths = []
    for path in candidates:
        normalized = os.path.abspath(os.path.expanduser(path))
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(normalized)
    return unique_paths


def render_smoked_salmon_tab(default_downloads_folder: str, locked: bool = False) -> None:
    _ui_salmon_debug(
        f"Rendering smoked-salmon tab. locked={locked}, default_downloads_folder_set={bool(default_downloads_folder)}."
    )
    st.subheader("🐟 Smoked Salmon Upload")
    st.caption(
        "Upload already-downloaded folders with `smoked-salmon` (GitHub: "
        "https://github.com/smokin-salmon/smoked-salmon)."
    )
    if locked:
        st.markdown(
            """
            <div style="
                margin: 0.4rem 0 1rem 0;
                padding: 0.9rem 1rem;
                border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.18);
                background: linear-gradient(135deg, rgba(0,0,0,0.72), rgba(20,20,20,0.78));
                color: #f2f2f2;
                font-weight: 600;
                font-size: 3rem;
                text-align: center;
                letter-spacing: 0.2px;
            ">
                WIP 🚧
            </div>
            """,
            unsafe_allow_html=True,
        )

    config_path = get_smoked_salmon_config_path()
    config_ok, config_init_msg = ensure_smoked_salmon_config_file(config_path)
    _ui_salmon_debug(
        f"Smoked-salmon config resolved. config_ok={config_ok}, config_path=`{config_path}`."
    )
    if config_init_msg:
        _ui_salmon_debug(f"Config init message shown: {config_init_msg}")
        st.info(config_init_msg)

    if "salmon_cfg_text" not in st.session_state:
        st.session_state.salmon_cfg_text = read_smoked_salmon_config_text(config_path) if config_ok else ""
    if "salmon_cmd_last_level" not in st.session_state:
        st.session_state.salmon_cmd_last_level = ""
    if "salmon_cmd_last_message" not in st.session_state:
        st.session_state.salmon_cmd_last_message = ""
    if "salmon_cmd_last_log_path" not in st.session_state:
        st.session_state.salmon_cmd_last_log_path = ""
    if "salmon_setup_status" not in st.session_state:
        st.session_state.salmon_setup_status = check_smoked_salmon_setup()
    if "salmon_install_last_level" not in st.session_state:
        st.session_state.salmon_install_last_level = ""
    if "salmon_install_last_message" not in st.session_state:
        st.session_state.salmon_install_last_message = ""
    if "salmon_install_last_log_path" not in st.session_state:
        st.session_state.salmon_install_last_log_path = ""

    with st.expander("⚙️ Smoked Salmon Settings", expanded=False):
        source = st.selectbox(
            "Release Source (-s)",
            options=SALMON_SOURCE_OPTIONS,
            index=SALMON_SOURCE_OPTIONS.index("WEB"),
            key="salmon_source",
            disabled=locked,
        )
        extra_args = st.text_input(
            "Additional CLI args",
            value="",
            key="salmon_extra_args",
            help="Optional flags appended to each `salmon up` command.",
            disabled=locked,
        )
        st.caption("Install command: `uv tool install git+https://github.com/smokin-salmon/smoked-salmon`")
        st.markdown("Prompt handling")
        lossy_master_choice = st.selectbox(
            "When prompted: Is this release lossy mastered?",
            options=[
                "Let salmon default",
                "Yes",
                "No",
                "Reopen spectrals",
                "Abort upload",
                "Delete music folder",
            ],
            index=0,
            key="salmon_lossy_master_choice",
            disabled=locked,
        )
        lossy_master_comment = st.text_area(
            "Lossy master comment (sent only when salmon asks for it)",
            key="salmon_lossy_master_comment",
            placeholder="Optional note shown in lossy approval report...",
            height=90,
            disabled=locked,
        )
        enable_ai_review = st.checkbox(
            "Enable AI metadata review (auto-answer Yes when asked)",
            key="salmon_enable_ai_review",
            disabled=locked,
        )
        ai_api_key = st.text_input(
            "AI API Key (required when AI review is enabled)",
            key="salmon_ai_api_key",
            type="password",
            disabled=locked,
        )
        ai_followup_choice = st.selectbox(
            "When AI suggests metadata updates",
            options=[
                "Keep original metadata",
                "Apply suggestions",
                "Prompt model and rerun",
            ],
            index=0,
            key="salmon_ai_followup_choice",
            disabled=locked,
        )
        ai_rerun_instruction = st.text_input(
            "AI rerun instruction (used only for 'Prompt model and rerun')",
            key="salmon_ai_rerun_instruction",
            disabled=locked,
        )
        custom_prompt_rules = st.text_area(
            "Custom prompt answers (one per line: prompt substring => answer)",
            key="salmon_custom_prompt_rules",
            height=160,
            placeholder=(
                "# Example\n"
                "would you still like to upload? => y\n"
                "what is the encoding of this release? [a]bort => LOSSLESS\n"
                "are the above tags acceptable? => y\n"
            ),
            disabled=locked,
        )

    with st.expander("🧪 Setup Assistant", expanded=True):
        _ui_salmon_debug("Rendering setup assistant section.")
        status = dict(st.session_state.salmon_setup_status or {})
        st.session_state.salmon_setup_status = status
        st.caption(
            "Checks required CLI tools and smoked-salmon availability. "
            "If setup is complete, uploads run immediately; if not, install is available."
        )
        st.caption(f"Detected config path: `{status.get('config_path', config_path)}`")

        if status.get("ready"):
            st.success("Setup looks ready: required tools + smoked-salmon are detected.")
        else:
            st.warning("Setup is incomplete.")
            missing_tools = status.get("missing_required_tools", [])
            if missing_tools:
                st.error("Missing required tools: " + ", ".join(missing_tools))
                hints = get_missing_tool_install_hints(missing_tools)
                commands = hints.get("commands", [])
                if commands:
                    label = hints.get("platform_label", "this system")
                    st.caption(f"Install command(s) for {label}:")
                    for cmd in commands:
                        st.code(cmd, language="bash" if os.name != "nt" else "powershell")
            if not status.get("has_salmon"):
                st.error("`salmon` command is not detected.")
            if status.get("has_uv"):
                st.info(f"Detected uv executable: `{status.get('uv_command', '')}`")
            else:
                st.info("`uv` is not detected. You can still click Install to get a full error log.")

        setup_col1, setup_col2 = st.columns([1.1, 2.4])
        with setup_col1:
            refresh_setup = st.button("Refresh Setup Check", key="salmon_setup_refresh", disabled=locked)
        with setup_col2:
            install_salmon = st.button(
                "Install smoked-salmon (auto-install uv if needed)",
                key="salmon_install_btn",
                type="primary",
                disabled=locked,
            )

        if refresh_setup:
            _ui_salmon_debug("Setup assistant: refresh setup clicked.")
            st.session_state.salmon_setup_status = check_smoked_salmon_setup()
            st.rerun()

        if install_salmon:
            _ui_salmon_debug("Setup assistant: install smoked-salmon clicked.")
            install_live_caption = st.empty()
            install_live_box = st.empty()

            def _update_install_log(log_path: str, tail_text: str) -> None:
                install_live_caption.caption(f"Live install log: {log_path}")
                install_live_box.code(tail_text or "(waiting for install output...)", language="text")

            with st.spinner("Installing smoked-salmon via uv..."):
                ok, msg, log_path = install_smoked_salmon_with_uv(progress_callback=_update_install_log)
            _ui_salmon_debug(f"Install action finished. ok={ok}, log_path=`{log_path}`.")
            _update_install_log(log_path, _read_log_tail(log_path))
            st.session_state.salmon_install_last_level = "success" if ok else "error"
            st.session_state.salmon_install_last_message = msg
            st.session_state.salmon_install_last_log_path = log_path
            st.session_state.salmon_setup_status = check_smoked_salmon_setup()
            st.rerun()

        if st.session_state.salmon_install_last_message:
            if st.session_state.salmon_install_last_level == "success":
                st.success(st.session_state.salmon_install_last_message)
            else:
                st.error(st.session_state.salmon_install_last_message)
        if (
            st.session_state.salmon_install_last_log_path
            and os.path.exists(st.session_state.salmon_install_last_log_path)
        ):
            with open(st.session_state.salmon_install_last_log_path, "r", encoding="utf-8") as f:
                install_log_text = f.read()
            st.download_button(
                "Download Last Install Log",
                data=install_log_text,
                file_name="smoked_salmon_install_last.log",
                mime="text/plain",
                key="salmon_install_log_download",
                disabled=locked,
            )

    with st.expander("🧩 Smoked Salmon Config (config.toml)", expanded=False):
        _ui_salmon_debug("Rendering smoked-salmon config editor section.")
        st.caption(f"Config path: `{config_path}`")
        cfg_col1, cfg_col2, cfg_col3 = st.columns([1.2, 1.2, 2.6])
        with cfg_col1:
            reload_cfg = st.button("Reload Config", key="salmon_cfg_reload", disabled=locked)
        with cfg_col2:
            save_cfg = st.button("Save Config", key="salmon_cfg_save", type="primary", disabled=locked)
        with cfg_col3:
            st.caption("Edit raw TOML config text below.")

        if reload_cfg:
            _ui_salmon_debug("Config editor: reload clicked.")
            st.session_state.salmon_cfg_text = read_smoked_salmon_config_text(config_path)
            st.rerun()
        if save_cfg:
            _ui_salmon_debug("Config editor: save clicked.")
            ok, msg = save_smoked_salmon_config_text(config_path, st.session_state.salmon_cfg_text)
            if ok:
                _ui_salmon_debug("Config editor save succeeded.")
                st.success(msg)
            else:
                _ui_salmon_debug(f"Config editor save failed: {msg}")
                st.error(msg)

        st.text_area(
            "config.toml",
            key="salmon_cfg_text",
            height=360,
            help="Any valid smoked-salmon TOML config is accepted.",
            disabled=locked,
        )

        st.markdown("Quick actions")
        act_col1, act_col2, act_col3 = st.columns(3)
        with act_col1:
            run_health = st.button("Run `salmon health`", key="salmon_health_btn", disabled=locked)
        with act_col2:
            run_checkconf = st.button("Run `salmon checkconf`", key="salmon_checkconf_btn", disabled=locked)
        with act_col3:
            run_migrate = st.button("Run `salmon migrate`", key="salmon_migrate_btn", disabled=locked)

        chosen_cmd = ""
        if run_health:
            chosen_cmd = "health"
        elif run_checkconf:
            chosen_cmd = "checkconf"
        elif run_migrate:
            chosen_cmd = "migrate"

        if chosen_cmd:
            _ui_salmon_debug(f"Quick action command triggered: `{chosen_cmd}`.")
            cmd_live_caption = st.empty()
            cmd_live_box = st.empty()

            def _update_cmd_log(log_path: str, tail_text: str) -> None:
                cmd_live_caption.caption(f"Live smoked-salmon command log: {log_path}")
                cmd_live_box.code(tail_text or "(waiting for command output...)", language="text")

            with st.spinner(f"Running `salmon {chosen_cmd}`..."):
                ok, msg, log_path = run_smoked_salmon_command(chosen_cmd, progress_callback=_update_cmd_log)
            _ui_salmon_debug(f"Quick command finished. ok={ok}, log_path=`{log_path}`.")
            _update_cmd_log(log_path, _read_log_tail(log_path))
            st.session_state.salmon_cmd_last_level = "success" if ok else "error"
            st.session_state.salmon_cmd_last_message = msg
            st.session_state.salmon_cmd_last_log_path = log_path
            st.rerun()

        if st.session_state.salmon_cmd_last_message:
            if st.session_state.salmon_cmd_last_level == "success":
                st.success(st.session_state.salmon_cmd_last_message)
            else:
                st.error(st.session_state.salmon_cmd_last_message)
        if st.session_state.salmon_cmd_last_log_path and os.path.exists(st.session_state.salmon_cmd_last_log_path):
            with open(st.session_state.salmon_cmd_last_log_path, "r", encoding="utf-8") as f:
                cmd_log_text = f.read()
            st.download_button(
                "Download Last Command Log",
                data=cmd_log_text,
                file_name="smoked_salmon_command_last.log",
                mime="text/plain",
                key="salmon_cmd_log_download",
                disabled=locked,
            )

    if "salmon_last_level" not in st.session_state:
        st.session_state.salmon_last_level = ""
    if "salmon_last_message" not in st.session_state:
        st.session_state.salmon_last_message = ""
    if "salmon_last_log_path" not in st.session_state:
        st.session_state.salmon_last_log_path = ""

    single_path = st.text_input(
        "Downloaded Album Folder Path",
        value=default_downloads_folder or "",
        key="salmon_single_album_path",
        help="Use one album folder, or fill the multi-path inputs below.",
        disabled=locked,
    )
    multi_paths = st.text_area(
        "Or paste multiple folder paths (one per line)",
        key="salmon_multi_paths",
        height=140,
        placeholder="/music/downloads/Artist - Album\n/music/downloads/Artist 2 - Album 2",
        disabled=locked,
    )
    uploaded_paths_file = st.file_uploader(
        "Or upload a file of folder paths",
        type=["txt", "log"],
        key="salmon_paths_upload",
        disabled=locked,
    )
    album_paths = _collect_album_paths(single_path, multi_paths, uploaded_paths_file)
    _ui_salmon_debug(f"Collected {len(album_paths)} album path(s) for upload run.")
    st.caption(f"Detected {len(album_paths)} unique folder path(s).")

    run_salmon_btn = st.button(
        "Run Smoked Salmon Upload",
        type="primary",
        key="salmon_run_btn",
        disabled=locked,
    )
    if run_salmon_btn:
        _ui_salmon_debug("Run smoked-salmon upload button clicked.")
        if not album_paths:
            _ui_salmon_debug("Upload run blocked: no album paths were provided.")
            st.warning("No folder paths detected. Add at least one target folder.")
        else:
            parsed_rules, parse_errors = _parse_prompt_rules(custom_prompt_rules)
            if parse_errors:
                _ui_salmon_debug(f"Upload run blocked: prompt rule parse errors={len(parse_errors)}.")
                st.error("Custom prompt rules have formatting errors:\n" + "\n".join(parse_errors))
                return
            if enable_ai_review and not ai_api_key.strip():
                _ui_salmon_debug("Upload run blocked: AI review enabled but API key missing.")
                st.error("AI metadata review is enabled, but AI API Key is empty.")
                return
            if enable_ai_review and ai_followup_choice == "Prompt model and rerun" and not ai_rerun_instruction.strip():
                _ui_salmon_debug("Upload run blocked: AI rerun option selected without instruction.")
                st.error("AI rerun instruction is required for 'Prompt model and rerun'.")
                return
            if enable_ai_review:
                _ui_salmon_debug("Applying AI review settings before upload run.")
                ok_ai, msg_ai = apply_smoked_salmon_ai_review_settings(
                    config_path,
                    enabled=True,
                    api_key=ai_api_key.strip(),
                )
                if not ok_ai:
                    _ui_salmon_debug(f"Upload run blocked: failed applying AI review settings: {msg_ai}")
                    st.error(msg_ai)
                    return
                parsed_rules["run ai metadata review?"] = "y"
                followup_map = {
                    "Keep original metadata": "k",
                    "Apply suggestions": "a",
                    "Prompt model and rerun": "p",
                }
                parsed_rules["[a]pply suggestions, [k]eep original, [p]rompt model and rerun"] = followup_map.get(
                    ai_followup_choice,
                    "k",
                )
                if ai_followup_choice == "Prompt model and rerun":
                    parsed_rules["what should the model change or prioritize?"] = ai_rerun_instruction.strip()

            current_setup = check_smoked_salmon_setup()
            st.session_state.salmon_setup_status = current_setup
            if not current_setup.get("has_salmon"):
                _ui_salmon_debug("Upload run detected missing `salmon` command.")
                if current_setup.get("has_uv"):
                    _ui_salmon_debug("Attempting pre-run install via uv.")
                    st.info("`salmon` not found. Attempting install with uv first...")
                    install_live_caption = st.empty()
                    install_live_box = st.empty()

                    def _update_install_log_on_run(log_path: str, tail_text: str) -> None:
                        install_live_caption.caption(f"Live install log: {log_path}")
                        install_live_box.code(tail_text or "(waiting for install output...)", language="text")

                    with st.spinner("Installing smoked-salmon via uv before upload..."):
                        ok, msg, log_path = install_smoked_salmon_with_uv(progress_callback=_update_install_log_on_run)
                    _ui_salmon_debug(f"Pre-run install finished. ok={ok}, log_path=`{log_path}`.")
                    _update_install_log_on_run(log_path, _read_log_tail(log_path))
                    st.session_state.salmon_install_last_level = "success" if ok else "error"
                    st.session_state.salmon_install_last_message = msg
                    st.session_state.salmon_install_last_log_path = log_path
                    current_setup = check_smoked_salmon_setup()
                    st.session_state.salmon_setup_status = current_setup
                    if not ok or not current_setup.get("has_salmon"):
                        _ui_salmon_debug("Upload run aborted: salmon still unavailable after install attempt.")
                        st.error("Could not continue: smoked-salmon is still not available.")
                        return
                else:
                    _ui_salmon_debug("Upload run aborted: salmon missing and uv unavailable.")
                    st.error("Could not continue: `salmon` is missing and `uv` is not available for auto-install.")
                    return

            live_log_caption = st.empty()
            live_log_box = st.empty()
            live_spectral_caption = st.empty()
            live_spectral_links = st.empty()
            live_spectral_images = st.empty()

            def _update_live_log(log_path: str, tail_text: str) -> None:
                live_log_caption.caption(f"Live smoked-salmon log: {log_path}")
                live_log_box.code(tail_text or "(waiting for smoked-salmon output...)", language="text")
                spectral_urls = _extract_spectral_urls(tail_text)
                if spectral_urls:
                    live_spectral_caption.caption("Detected spectral/lossy URLs from live log:")
                    live_spectral_links.markdown("\n".join([f"- {url}" for url in spectral_urls[:12]]))
                    try:
                        live_spectral_images.image(spectral_urls[:8], width=280)
                    except Exception:
                        pass

            with st.spinner("Running smoked-salmon uploads..."):
                lossy_choice_map = {
                    "Let salmon default": "",
                    "Yes": "y",
                    "No": "n",
                    "Reopen spectrals": "r",
                    "Abort upload": "a",
                    "Delete music folder": "d",
                }
                success_count, attempted, failures, log_path = run_smoked_salmon_uploads(
                    album_paths,
                    source=source,
                    extra_args=extra_args,
                    lossy_master_choice=lossy_choice_map.get(lossy_master_choice, ""),
                    lossy_master_comment=lossy_master_comment,
                    custom_prompt_responses=parsed_rules,
                    fail_on_unhandled_prompt=True,
                    progress_callback=_update_live_log,
                )
            _ui_salmon_debug(
                f"Upload run finished. attempted={attempted}, success_count={success_count}, failures={len(failures)}."
            )
            _update_live_log(log_path, _read_log_tail(log_path))
            st.session_state.salmon_last_log_path = log_path
            if failures:
                st.session_state.salmon_last_level = "error"
                st.session_state.salmon_last_message = (
                    f"smoked-salmon attempted {attempted} folder(s) with errors:\n" + "\n".join(failures)
                )
            else:
                st.session_state.salmon_last_level = "success"
                st.session_state.salmon_last_message = (
                    f"smoked-salmon upload finished for {success_count} folder(s)."
                )
            st.rerun()

    if st.session_state.salmon_last_message:
        if st.session_state.salmon_last_level == "success":
            st.success(st.session_state.salmon_last_message)
        elif st.session_state.salmon_last_level == "error":
            st.error(st.session_state.salmon_last_message)
        else:
            st.info(st.session_state.salmon_last_message)
    if st.session_state.salmon_last_log_path and os.path.exists(st.session_state.salmon_last_log_path):
        st.caption(f"Last smoked-salmon log: {st.session_state.salmon_last_log_path}")
        with open(st.session_state.salmon_last_log_path, "r", encoding="utf-8") as f:
            log_text = f.read()
        st.download_button(
            "Download Smoked Salmon Log",
            data=log_text,
            file_name="smoked_salmon_last.log",
            mime="text/plain",
            key="salmon_log_download",
            disabled=locked,
        )
        st.text_area(
            "Smoked Salmon Log (tail)",
            value=log_text[-4000:],
            height=220,
            key="salmon_log_tail",
            disabled=locked,
        )
        spectral_urls = _extract_spectral_urls(log_text)
        if spectral_urls:
            st.caption("Spectral/Lossy URLs detected in last log:")
            st.markdown("\n".join([f"- {url}" for url in spectral_urls[:20]]))
            try:
                st.image(spectral_urls[:10], width=280)
            except Exception:
                pass
