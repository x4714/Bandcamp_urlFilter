import asyncio
import os
import uuid
from datetime import date, datetime
from io import StringIO
from threading import Lock, Thread
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app_modules.filtering import build_filtered_entries, validate_filters
from app_modules.matching import process_batch
from app_modules.smoked_salmon import (
    check_smoked_salmon_setup,
    ensure_smoked_salmon_config_file,
    get_smoked_salmon_config_path,
)
from app_modules.streamrip import (
    CODEC_OPTIONS,
    QUALITY_OPTIONS,
    discover_qobuz_app_id,
    ensure_streamrip_config_file,
    export_qobuz_batches,
    extract_qobuz_urls,
    format_quality_option,
    get_streamrip_config_path,
    load_streamrip_settings,
    run_streamrip_batches,
    save_streamrip_settings,
)

load_dotenv(override=True)

app = FastAPI(title="Bandcamp to Qobuz Matcher")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

_SESSION_STORE: dict[str, dict[str, Any]] = {}
_STORE_LOCK = Lock()
_APP_ID_FETCH_LOCK = Lock()
_APP_ID_FETCH: dict[str, Any] = {
    "state": "idle",
    "message": "App ID fetch not started yet.",
    "app_id": "",
}

TABS = ["Bandcamp Matcher", "Direct Qobuz Rip", "Smoked Salmon Upload"]
QOBUZ_HELP_TEXT = (
    "Get token from Qobuz Web Player: open devtools network tab, capture a request with "
    "`x-user-auth-token`, then paste it into `.env` as `QOBUZ_USER_AUTH_TOKEN`."
)
QOBUZ_ENV_HINT_TEXT = (
    "Use `.env` in the project root to set `QOBUZ_USER_AUTH_TOKEN` (and optional `QOBUZ_APP_ID`)."
)
QOBUZ_TOKEN_MISSING_TEXT = "QOBUZ_USER_AUTH_TOKEN is missing. Add it in .env then run again, or enable Dry Run."


def _default_state() -> dict[str, Any]:
    return {
        "active_tab": "Bandcamp Matcher",
        "messages": [],
        "matcher_results": [],
        "matcher_filtered": [],
        "matcher_status": "",
        "matcher_last_export": "",
        "matcher_rip_log_tail": "",
        "direct_urls": [],
        "direct_status": "",
        "direct_log_tail": "",
        "settings": {
            "tag": "",
            "location": "",
            "min_tracks": "",
            "max_tracks": "",
            "min_duration": "",
            "max_duration": "",
            "start_date": "",
            "end_date": "",
            "free_mode": "All",
            "dry_run": False,
            "rip_quality": 3,
            "rip_codec": "Original",
            "max_links": 10,
            "auto_rip_after_export": False,
            "streamrip_form": {},
            "wip_matcher": False,
            "wip_direct_rip": False,
            "wip_smoked_salmon": True,
        },
    }


def _app_id_fetch_snapshot() -> dict[str, Any]:
    with _APP_ID_FETCH_LOCK:
        return {
            "state": str(_APP_ID_FETCH.get("state", "idle")),
            "message": str(_APP_ID_FETCH.get("message", "")),
            "app_id": str(_APP_ID_FETCH.get("app_id", "")),
        }


def _set_app_id_fetch_state(state: str, message: str, app_id: str = "") -> None:
    with _APP_ID_FETCH_LOCK:
        _APP_ID_FETCH["state"] = state
        _APP_ID_FETCH["message"] = message
        _APP_ID_FETCH["app_id"] = app_id


def _start_app_id_discovery_if_needed() -> None:
    load_dotenv(override=True)
    env_app_id = os.getenv("QOBUZ_APP_ID", "").strip()
    if env_app_id:
        _set_app_id_fetch_state("env", "Using QOBUZ_APP_ID from .env.", env_app_id)
        return

    with _APP_ID_FETCH_LOCK:
        current_state = str(_APP_ID_FETCH.get("state", "idle"))
        if current_state in {"running", "success", "error", "env"}:
            return
        _APP_ID_FETCH["state"] = "running"
        _APP_ID_FETCH["message"] = "QOBUZ_APP_ID not set. Discovering from play.qobuz.com..."
        _APP_ID_FETCH["app_id"] = ""

    def _run_discovery() -> None:
        def _status(message: str) -> None:
            _set_app_id_fetch_state("running", message)

        app_id = ""
        try:
            app_id = discover_qobuz_app_id(status_callback=_status).strip()
        except Exception as exc:
            _set_app_id_fetch_state("error", f"App ID discovery failed: {exc}")
            return

        if app_id:
            _set_app_id_fetch_state("success", f"Qobuz App ID discovered: {app_id}", app_id)
        else:
            _set_app_id_fetch_state(
                "error",
                "Could not auto-discover QOBUZ_APP_ID. You can set it manually in .env or in Streamrip setup.",
            )

    Thread(target=_run_discovery, daemon=True).start()


def _state_for(request: Request) -> tuple[str, dict[str, Any]]:
    sid = request.cookies.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
    with _STORE_LOCK:
        if sid not in _SESSION_STORE:
            _SESSION_STORE[sid] = _default_state()
        return sid, _SESSION_STORE[sid]


def _ctx(request: Request, state: dict[str, Any]) -> dict[str, Any]:
    streamrip_context = _load_streamrip_context()
    env_qobuz_token = str(streamrip_context.get("env_qobuz_token", "")).strip()
    if env_qobuz_token and state.get("messages"):
        stale_messages = {QOBUZ_HELP_TEXT, QOBUZ_ENV_HINT_TEXT, QOBUZ_TOKEN_MISSING_TEXT}
        state["messages"] = [
            m for m in state.get("messages", []) if str(m.get("text", "")) not in stale_messages
        ]
    state["settings"]["streamrip_form"] = streamrip_context["streamrip_settings"]
    smoked_config_path = get_smoked_salmon_config_path()
    smoked_config_ready, smoked_config_message = ensure_smoked_salmon_config_file(smoked_config_path)
    smoked_status = check_smoked_salmon_setup()
    return {
        "request": request,
        "tabs": TABS,
        "active_tab": state.get("active_tab", "Bandcamp Matcher"),
        "state": state,
        "quality_options": QUALITY_OPTIONS,
        "codec_options": CODEC_OPTIONS,
        "format_quality_option": format_quality_option,
        "smoked_config_path": smoked_config_path,
        "smoked_config_ready": smoked_config_ready,
        "smoked_config_message": smoked_config_message,
        "smoked_status": smoked_status,
        **streamrip_context,
    }


def _load_streamrip_context() -> dict[str, Any]:
    config_path = get_streamrip_config_path()
    config_ready, config_message = ensure_streamrip_config_file(config_path)
    settings = {}
    settings_error = ""
    if config_ready:
        settings, settings_error = load_streamrip_settings(config_path)

    load_dotenv(override=True)
    env_qobuz_app_id = os.getenv("QOBUZ_APP_ID", "").strip()
    env_qobuz_token = os.getenv("QOBUZ_USER_AUTH_TOKEN", "").strip()
    if not env_qobuz_app_id:
        _start_app_id_discovery_if_needed()
    app_id_fetch = _app_id_fetch_snapshot()
    if not env_qobuz_app_id and app_id_fetch.get("app_id"):
        env_qobuz_app_id = str(app_id_fetch.get("app_id", "")).strip()

    default_quality = int(settings.get("quality", 3)) if settings else 3
    if default_quality not in QUALITY_OPTIONS:
        default_quality = 3

    default_codec = str(settings.get("codec_selection", "Original")) if settings else "Original"
    if default_codec not in CODEC_OPTIONS:
        default_codec = "Original"

    has_identifier = bool(str(settings.get("email_or_userid", "")).strip())
    has_token = bool(str(settings.get("password_or_token", "")).strip())
    has_folder = bool(str(settings.get("downloads_folder", "")).strip())
    has_db_path = bool(str(settings.get("downloads_db_path", "")).strip())
    has_failed_path = bool(str(settings.get("failed_downloads_path", "")).strip())
    streamrip_needs_setup = not config_ready or not settings or not (has_identifier and has_token and has_folder and has_db_path and has_failed_path)

    return {
        "streamrip_config_path": config_path,
        "streamrip_config_ready": config_ready,
        "streamrip_config_init_msg": config_message,
        "streamrip_settings": settings,
        "streamrip_settings_error": settings_error,
        "env_qobuz_app_id": env_qobuz_app_id,
        "env_qobuz_token": env_qobuz_token,
        "app_id_fetch": app_id_fetch,
        "default_rip_quality": default_quality,
        "default_codec": default_codec,
        "streamrip_needs_setup": streamrip_needs_setup,
    }


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _push_message(state: dict[str, Any], level: str, text: str) -> None:
    state.setdefault("messages", []).append({"level": level, "text": text})


def _render_tab(request: Request, state: dict[str, Any]) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/tab_content.html",
        context=_ctx(request, state),
    )


def _render_tab_and_sidebar(request: Request, state: dict[str, Any]) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/tab_content_with_sidebar.html",
        context=_ctx(request, state),
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    sid, state = _state_for(request)
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_ctx(request, state),
    )
    response.set_cookie("sid", sid, httponly=True, samesite="lax")
    return response


@app.get("/tabs/{tab_name}", response_class=HTMLResponse)
def switch_tab(
    tab_name: str,
    request: Request,
    preview: bool = Query(default=False),
) -> HTMLResponse:
    _, state = _state_for(request)
    if tab_name not in TABS:
        return _render_tab_and_sidebar(request, state)

    if preview:
        # Render the requested tab for client-side prefetch without mutating session state.
        preview_state = {**state, "active_tab": tab_name}
        return _render_tab_and_sidebar(request, preview_state)

    state["active_tab"] = tab_name
    return _render_tab_and_sidebar(request, state)


@app.get("/partials/app-id-fetch-status", response_class=HTMLResponse)
def app_id_fetch_status(request: Request) -> HTMLResponse:
    _, state = _state_for(request)
    return templates.TemplateResponse(
        request=request,
        name="partials/app_id_fetch_status.html",
        context=_ctx(request, state),
    )


@app.post("/actions/open-env", response_class=HTMLResponse)
def open_env_action(request: Request) -> HTMLResponse:
    _, state = _state_for(request)
    state["messages"] = []
    env_path = ".env"
    if not os.path.exists(env_path):
        template = """# Important: So that Python recognizes local directories (e.g., logic) as modules
PYTHONPATH=.
# Optional: Set your own Qobuz App ID (if omitted, the app auto-fetches it from Qobuz Web Player)
# QOBUZ_APP_ID=
# Required (depending on region/account type): Set your user Auth Token for Qobuz
QOBUZ_USER_AUTH_TOKEN="""
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(template)
        except OSError as exc:
            _push_message(state, "error", f"Could not create .env: {exc}")
            return _render_tab_and_sidebar(request, state)
    _push_message(state, "info", QOBUZ_ENV_HINT_TEXT)
    return _render_tab_and_sidebar(request, state)


@app.post("/actions/qobuz-help", response_class=HTMLResponse)
def qobuz_help_action(request: Request) -> HTMLResponse:
    _, state = _state_for(request)
    state["messages"] = []
    load_dotenv(override=True)
    if os.getenv("QOBUZ_USER_AUTH_TOKEN", "").strip():
        _push_message(state, "success", "QOBUZ_USER_AUTH_TOKEN is already set in `.env`.")
        return _render_tab_and_sidebar(request, state)
    _push_message(
        state,
        "info",
        QOBUZ_HELP_TEXT,
    )
    return _render_tab_and_sidebar(request, state)


@app.post("/actions/set-wip", response_class=HTMLResponse)
def set_wip(
    request: Request,
    wip_matcher: bool = Form(default=False),
    wip_direct_rip: bool = Form(default=False),
    wip_smoked_salmon: bool = Form(default=False),
) -> HTMLResponse:
    _, state = _state_for(request)
    state["settings"]["wip_matcher"] = wip_matcher
    state["settings"]["wip_direct_rip"] = wip_direct_rip
    state["settings"]["wip_smoked_salmon"] = wip_smoked_salmon
    return _render_tab_and_sidebar(request, state)


@app.post("/actions/save-streamrip", response_class=HTMLResponse)
def save_streamrip(
    request: Request,
    use_auth_token: bool = Form(default=False),
    email_or_userid: str = Form(default=""),
    password_or_token: str = Form(default=""),
    app_id: str = Form(default=""),
    downloads_folder: str = Form(default=""),
    downloads_db_path: str = Form(default=""),
    failed_downloads_path: str = Form(default=""),
    quality: int = Form(default=3),
    codec_selection: str = Form(default="Original"),
) -> HTMLResponse:
    _, state = _state_for(request)
    state["messages"] = []
    context = _load_streamrip_context()

    ok, msg = save_streamrip_settings(
        context["streamrip_config_path"],
        use_auth_token=use_auth_token,
        email_or_userid=email_or_userid,
        password_or_token=password_or_token,
        app_id=app_id,
        quality=quality,
        codec_selection=codec_selection,
        downloads_folder=downloads_folder,
        downloads_db_path=downloads_db_path,
        failed_downloads_path=failed_downloads_path,
    )

    state["settings"]["rip_quality"] = quality
    state["settings"]["rip_codec"] = codec_selection
    _push_message(state, "success" if ok else "error", msg)

    return _render_tab_and_sidebar(request, state)


@app.post("/actions/process-matcher", response_class=HTMLResponse)
def process_matcher(
    request: Request,
    upload: UploadFile | None = File(default=None),
    tag: str = Form(default=""),
    location: str = Form(default=""),
    min_tracks: str = Form(default=""),
    max_tracks: str = Form(default=""),
    min_duration: str = Form(default=""),
    max_duration: str = Form(default=""),
    start_date: str = Form(default=""),
    end_date: str = Form(default=""),
    free_mode: str = Form(default="All"),
    dry_run: bool = Form(default=False),
    auto_rip_after_export: bool = Form(default=False),
    max_links: int = Form(default=10),
    rip_quality: int = Form(default=3),
    rip_codec: str = Form(default="Original"),
) -> HTMLResponse:
    _, state = _state_for(request)
    state["active_tab"] = "Bandcamp Matcher"
    state["messages"] = []
    state["matcher_last_export"] = ""
    state["matcher_rip_log_tail"] = ""

    if state["settings"].get("wip_matcher"):
        _push_message(state, "warning", "Bandcamp Matcher is currently WIP-locked.")
        return _render_tab_and_sidebar(request, state)

    state["settings"].update(
        {
            "tag": tag,
            "location": location,
            "min_tracks": min_tracks,
            "max_tracks": max_tracks,
            "min_duration": min_duration,
            "max_duration": max_duration,
            "start_date": start_date,
            "end_date": end_date,
            "free_mode": free_mode,
            "dry_run": dry_run,
            "rip_quality": rip_quality,
            "rip_codec": rip_codec,
            "max_links": max(1, int(max_links)),
            "auto_rip_after_export": auto_rip_after_export,
        }
    )

    min_tracks_i = _to_int(min_tracks)
    max_tracks_i = _to_int(max_tracks)
    min_duration_i = _to_int(min_duration)
    max_duration_i = _to_int(max_duration)
    start_d = _to_date(start_date)
    end_d = _to_date(end_date)

    validation_errors = validate_filters(
        min_tracks_i,
        max_tracks_i,
        min_duration_i,
        max_duration_i,
        start_d,
        end_d,
    )
    if validation_errors:
        for err in validation_errors:
            _push_message(state, "error", err)
        return _render_tab_and_sidebar(request, state)

    if upload is None or not upload.filename:
        _push_message(state, "error", "Please upload a .txt or .log file first.")
        return _render_tab_and_sidebar(request, state)

    content = upload.file.read().decode("utf-8", errors="ignore")
    lines = StringIO(content).readlines()

    filter_config = {
        "tag": tag,
        "location": location,
        "min_tracks": min_tracks_i,
        "max_tracks": max_tracks_i,
        "min_duration": min_duration_i,
        "max_duration": max_duration_i,
        "free_mode": free_mode,
    }

    filtered_entries = build_filtered_entries(lines, filter_config, start_d, end_d)
    state["matcher_filtered"] = [
        {
            "url": e.url,
            "artist": e.artist,
            "title": e.title,
            "genre": e.genre,
            "tracks": e.track_count,
            "duration": e.duration_min,
        }
        for e in filtered_entries
    ]

    state["matcher_status"] = (
        f"Found {len(filtered_entries)} unique URLs matching your filters out of {len(lines)} total lines."
    )

    if not filtered_entries:
        _push_message(state, "info", "No URLs matched the filter criteria.")
        state["matcher_results"] = []
        return _render_tab_and_sidebar(request, state)

    if dry_run:
        _push_message(state, "info", "Dry run enabled. Qobuz matching skipped.")
        state["matcher_results"] = []
        return _render_tab_and_sidebar(request, state)

    load_dotenv(override=True)
    if not os.getenv("QOBUZ_USER_AUTH_TOKEN"):
        _push_message(
            state,
            "error",
            QOBUZ_TOKEN_MISSING_TEXT,
        )
        return _render_tab_and_sidebar(request, state)

    rows: list[dict[str, Any]] = []
    batch_size = 5
    for i in range(0, len(filtered_entries), batch_size):
        rows.extend(asyncio.run(process_batch(filtered_entries[i : i + batch_size])))

    state["matcher_results"] = rows
    matched_qobuz_urls = [r["Qobuz Link"] for r in rows if r.get("Qobuz Link")]
    _push_message(
        state,
        "success",
        f"Complete! Found {len(matched_qobuz_urls)} out of {len(filtered_entries)} matches.",
    )

    return _render_tab_and_sidebar(request, state)


@app.post("/actions/export-matcher", response_class=HTMLResponse)
def export_matcher(
    request: Request,
    max_links: int = Form(default=10),
    auto_rip_after_export: bool = Form(default=False),
    run_rip_now: bool = Form(default=False),
) -> HTMLResponse:
    _, state = _state_for(request)
    state["active_tab"] = "Bandcamp Matcher"
    state["messages"] = []
    state["settings"]["max_links"] = max(1, int(max_links))
    state["settings"]["auto_rip_after_export"] = auto_rip_after_export

    if state["settings"].get("wip_matcher"):
        _push_message(state, "warning", "Bandcamp Matcher is currently WIP-locked.")
        return _render_tab_and_sidebar(request, state)

    matched_qobuz_urls = [r.get("Qobuz Link", "") for r in state.get("matcher_results", []) if r.get("Qobuz Link")]
    if not matched_qobuz_urls:
        _push_message(state, "warning", "No matched Qobuz links found in the current results.")
        return _render_tab_and_sidebar(request, state)

    rip_quality = int(state["settings"].get("rip_quality", 3))
    rip_codec = str(state["settings"].get("rip_codec", "Original"))
    batch_files, total_batches = export_qobuz_batches(
        matched_qobuz_urls,
        max(1, int(max_links)),
        rip_quality,
        rip_codec,
    )
    state["matcher_last_export"] = (
        f"Created {total_batches} batch file(s): {', '.join(batch_files)}"
    )
    _push_message(state, "success", state["matcher_last_export"])

    should_run_rip = bool(run_rip_now or auto_rip_after_export)
    if should_run_rip:
        streamrip_ctx = _load_streamrip_context()
        if streamrip_ctx["streamrip_needs_setup"]:
            _push_message(state, "warning", "Streamrip setup is incomplete. Skipped rip.")
            return _render_tab_and_sidebar(request, state)

        success_count, total_urls, failures, log_path = run_streamrip_batches(
            batch_files,
            rip_quality,
            rip_codec,
        )
        if failures:
            _push_message(state, "error", f"Rip had {len(failures)} errors. Log: {log_path}")
        else:
            _push_message(
                state,
                "success",
                f"Rip finished for {success_count} batch file(s) / {total_urls} URL(s).",
            )
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                state["matcher_rip_log_tail"] = f.read()[-5000:]
        except OSError:
            state["matcher_rip_log_tail"] = ""

    return _render_tab_and_sidebar(request, state)


@app.post("/actions/direct-rip", response_class=HTMLResponse)
def direct_rip(
    request: Request,
    pasted_urls: str = Form(default=""),
    uploaded_links: UploadFile | None = File(default=None),
    rip_quality: int = Form(default=3),
    rip_codec: str = Form(default="Original"),
) -> HTMLResponse:
    _, state = _state_for(request)
    state["active_tab"] = "Direct Qobuz Rip"
    state["messages"] = []

    if state["settings"].get("wip_direct_rip"):
        _push_message(state, "warning", "Direct Qobuz Rip is currently WIP-locked.")
        return _render_tab_and_sidebar(request, state)
    state["settings"]["rip_quality"] = rip_quality
    state["settings"]["rip_codec"] = rip_codec

    uploaded_text = ""
    if uploaded_links is not None and uploaded_links.filename:
        uploaded_text = uploaded_links.file.read().decode("utf-8", errors="ignore")

    merged = f"{pasted_urls}\n{uploaded_text}".strip()
    urls = extract_qobuz_urls(merged)
    state["direct_urls"] = urls

    if not urls:
        _push_message(state, "warning", "No Qobuz URLs detected.")
        return _render_tab_and_sidebar(request, state)

    streamrip_ctx = _load_streamrip_context()
    if streamrip_ctx["streamrip_needs_setup"]:
        _push_message(state, "error", "Complete Streamrip setup before direct rip.")
        return _render_tab_and_sidebar(request, state)

    batch_files, total_batches = export_qobuz_batches(urls, max(1, len(urls)), rip_quality, rip_codec)
    success_count, total_urls, failures, log_path = run_streamrip_batches(batch_files, rip_quality, rip_codec)

    if failures:
        _push_message(state, "error", f"Direct rip processed {total_urls} URL(s) with {len(failures)} errors. Log: {log_path}")
    else:
        _push_message(
            state,
            "success",
            f"Direct rip finished for {success_count} batch file(s) / {total_urls} URL(s).",
        )
    state["direct_status"] = f"Prepared {total_batches} batch file(s)."

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            state["direct_log_tail"] = f.read()[-5000:]
    except OSError:
        state["direct_log_tail"] = ""

    return _render_tab_and_sidebar(request, state)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
