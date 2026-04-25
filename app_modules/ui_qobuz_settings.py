import os
from collections.abc import Callable
from datetime import datetime, timezone

import streamlit as st

from app_modules.qobuz_utils import (
    parse_utc_datetime,
    qobuz_account_days_until_expiry,
    token_fingerprint,
)
from app_modules.streamrip import (
    fetch_qobuz_account_info,
    load_streamrip_settings,
    save_streamrip_settings,
)
from app_modules.time_utils import format_app_datetime, get_app_timezone_name
from app_modules.ui_state import remember_session_snapshot_value


def _pick_streamrip_identifier_from_account(account_data: dict, fallback: str = "") -> str:
    if not isinstance(account_data, dict):
        return str(fallback or "").strip()
    for key in ("user_id", "identifier", "login", "email"):
        candidate = str(account_data.get(key, "")).strip()
        if candidate:
            return candidate
    return str(fallback or "").strip()


def _should_refresh_qobuz_account_info(cache: dict, app_id: str, token: str) -> bool:
    if not isinstance(cache, dict) or not cache:
        return True
    if str(cache.get("app_id", "")) != str(app_id):
        return True
    if str(cache.get("token_fingerprint", "")) != token_fingerprint(token):
        return True

    fetched_at = parse_utc_datetime(str(cache.get("fetched_at", "")))
    if fetched_at is None:
        return True

    ok = bool(cache.get("ok", False))
    today = datetime.now(timezone.utc).date()
    if not ok:
        return fetched_at.date() != today

    days_left = qobuz_account_days_until_expiry(str(cache.get("subscription_expires_at", "")))
    if days_left is None:
        return False
    if days_left > 7:
        return False
    return fetched_at.date() != today


def _get_session_dict(key: str) -> dict:
    value = st.session_state.get(key)
    if isinstance(value, dict):
        return value
    normalized: dict = {}
    st.session_state[key] = normalized
    return normalized


def render_qobuz_settings_tab(
    streamrip_settings: dict,
    streamrip_settings_error: str,
    streamrip_config_path: str,
    streamrip_config_ready: bool,
    streamrip_config_init_msg: str,
    default_rip_quality: int,
    default_codec: str,
    default_downloads_folder: str,
    env_qobuz_app_id: str,
    env_qobuz_token: str,
    app_debug: Callable[[str], None],
    open_env_for_qobuz: Callable[[], None],
    cache_streamrip_runtime_state: Callable[[str, bool, str, dict, str, str, str], None],
) -> tuple[dict, str]:
    st.subheader("🔐 Qobuz Settings")
    st.caption("Manage Qobuz auth and view account/subscription details.")

    configured_streamrip_app_id = str(streamrip_settings.get("app_id", "")).strip()
    active_qobuz_app_id = configured_streamrip_app_id or str(env_qobuz_app_id or "").strip()
    token_present = bool(str(env_qobuz_token or "").strip())
    env_app_id_present = bool(str(os.getenv("QOBUZ_APP_ID", "")).strip())

    if token_present:
        st.success("`QOBUZ_USER_AUTH_TOKEN` is available.")
    else:
        st.warning("`QOBUZ_USER_AUTH_TOKEN` is missing in `.env`.")

    if configured_streamrip_app_id:
        st.info("Using Qobuz App ID saved in Streamrip settings.")
    elif env_app_id_present:
        st.info("Using Qobuz App ID from `.env`.")
    elif active_qobuz_app_id:
        st.info("Using auto-discovered Qobuz App ID.")
    else:
        st.warning("No Qobuz App ID available yet. Save one below or enable auto-discovery.")

    with st.form("qobuz_app_id_form"):
        qobuz_app_id_input = st.text_input(
            "Qobuz App ID",
            value=active_qobuz_app_id,
            help="Saved into Streamrip settings so `.env` App ID is optional.",
        )
        save_qobuz_app_id = st.form_submit_button("Save App ID To Streamrip Settings")
    if save_qobuz_app_id:
        if not streamrip_config_ready:
            st.error("Streamrip config is not ready yet. Open Streamrip Settings and initialize it first.")
        else:
            ok_save, msg_save = save_streamrip_settings(
                streamrip_config_path,
                use_auth_token=bool(streamrip_settings.get("use_auth_token", True)),
                email_or_userid=str(streamrip_settings.get("email_or_userid", "")),
                password_or_token=str(streamrip_settings.get("password_or_token", "")).strip() or str(env_qobuz_token or ""),
                app_id=str(qobuz_app_id_input or "").strip(),
                quality=int(streamrip_settings.get("quality", default_rip_quality)),
                codec_selection=str(streamrip_settings.get("codec_selection", default_codec)),
                downloads_folder=str(streamrip_settings.get("downloads_folder", "")).strip() or default_downloads_folder,
                downloads_db_path=str(streamrip_settings.get("downloads_db_path", "")),
                failed_downloads_path=str(streamrip_settings.get("failed_downloads_path", "")),
            )
            if ok_save:
                app_debug("Qobuz settings: saved app ID to streamrip config.")
                st.success("Saved Qobuz App ID to Streamrip settings.")
                st.rerun()
            else:
                st.error(msg_save)

    q_col1, q_col2 = st.columns(2)
    with q_col1:
        if st.button("📝 Open .env for Qobuz Token", help="Open `.env` to set/update Qobuz token values."):
            app_debug("Qobuz settings action: Open .env clicked.")
            open_env_for_qobuz()
    with q_col2:
        refresh_account_info = st.button(
            "Refresh Account Info",
            help="Fetch latest account data now from Qobuz.",
        )

    cache_key = "qobuz_account_info_cache"
    account_cache = _get_session_dict(cache_key)

    can_fetch_account_info = bool(active_qobuz_app_id and env_qobuz_token)
    if can_fetch_account_info and (
        refresh_account_info or _should_refresh_qobuz_account_info(account_cache, active_qobuz_app_id, env_qobuz_token)
    ):
        with st.spinner("Fetching Qobuz account details..."):
            ok_info, info_data, info_msg = fetch_qobuz_account_info(active_qobuz_app_id, env_qobuz_token)
        normalized_cache = {
            "ok": bool(ok_info),
            "message": str(info_msg or ""),
            "app_id": str(active_qobuz_app_id),
            "token_fingerprint": token_fingerprint(env_qobuz_token),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": dict(info_data or {}),
            "subscription_expires_at": str(info_data.get("subscription_expires_at", "")) if isinstance(info_data, dict) else "",
        }
        st.session_state[cache_key] = normalized_cache
        remember_session_snapshot_value(cache_key, normalized_cache)
        account_cache = normalized_cache
        if ok_info and streamrip_config_ready and streamrip_settings:
            current_streamrip_token = str(streamrip_settings.get("password_or_token", "")).strip()
            current_streamrip_identifier = str(streamrip_settings.get("email_or_userid", "")).strip()
            resolved_identifier = _pick_streamrip_identifier_from_account(info_data, current_streamrip_identifier)
            should_sync_to_streamrip = (
                current_streamrip_token != str(env_qobuz_token or "").strip()
                or (resolved_identifier and resolved_identifier != current_streamrip_identifier)
            )
            if should_sync_to_streamrip:
                sync_ok, sync_msg = save_streamrip_settings(
                    streamrip_config_path,
                    use_auth_token=True,
                    email_or_userid=resolved_identifier,
                    password_or_token=str(env_qobuz_token or "").strip(),
                    app_id=str(active_qobuz_app_id or "").strip(),
                    quality=int(streamrip_settings.get("quality", default_rip_quality)),
                    codec_selection=str(streamrip_settings.get("codec_selection", default_codec)),
                    downloads_folder=str(streamrip_settings.get("downloads_folder", "")).strip() or default_downloads_folder,
                    downloads_db_path=str(streamrip_settings.get("downloads_db_path", "")),
                    failed_downloads_path=str(streamrip_settings.get("failed_downloads_path", "")),
                )
                if sync_ok:
                    streamrip_settings, streamrip_settings_error = load_streamrip_settings(streamrip_config_path)
                    cache_streamrip_runtime_state(
                        streamrip_config_path,
                        streamrip_config_ready,
                        streamrip_config_init_msg,
                        streamrip_settings,
                        streamrip_settings_error,
                        env_qobuz_app_id,
                        env_qobuz_token,
                    )
                    st.session_state.qobuz_autofill_notice = (
                        "Qobuz token was validated in Qobuz Settings and Streamrip was auto-updated "
                        f"(token, App ID, identifier: `{resolved_identifier}`)."
                    )
                    remember_session_snapshot_value("qobuz_autofill_notice", st.session_state.qobuz_autofill_notice)
                    st.success(st.session_state.qobuz_autofill_notice)
                else:
                    app_debug(f"Qobuz settings token sync to streamrip failed: {sync_msg}")

    account_ok = bool(account_cache.get("ok", False))
    account_data = dict(account_cache.get("data", {}) or {})
    account_msg = str(account_cache.get("message", "")).strip()
    fetched_at = parse_utc_datetime(str(account_cache.get("fetched_at", "")))
    subscription_expires_at = parse_utc_datetime(str(account_data.get("subscription_expires_at", "")))
    next_renewal_at = parse_utc_datetime(str(account_data.get("next_renewal_at", "")))
    days_left = qobuz_account_days_until_expiry(str(account_cache.get("subscription_expires_at", "")))

    st.markdown("### Account Status")
    if not can_fetch_account_info:
        st.caption("Set both token and App ID to fetch account details.")
    elif account_ok:
        if days_left is not None:
            if days_left < 0:
                st.error(f"Subscription appears expired ({abs(days_left)} day(s) ago).")
            elif days_left <= 7:
                st.warning(f"Subscription expires in {days_left} day(s). This check refreshes once per day.")
            else:
                st.success(f"Subscription valid for {days_left} day(s).")
        elif account_msg:
            st.info(account_msg)
    elif account_msg:
        st.warning(account_msg)

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Identifier", value=str(account_data.get("identifier", "")), disabled=True)
        st.text_input("Email", value=str(account_data.get("email", "")), disabled=True)
        st.text_input("User ID", value=str(account_data.get("user_id", "")), disabled=True)
        st.text_input("Login", value=str(account_data.get("login", "")), disabled=True)
    with c2:
        st.text_input("Country", value=str(account_data.get("country", "")), disabled=True)
        st.text_input("Plan", value=str(account_data.get("subscription_plan", "")), disabled=True)
        st.text_input("Status", value=str(account_data.get("subscription_status", "")), disabled=True)
        st.text_input(
            f"Subscription Expires At ({get_app_timezone_name()})",
            value=(
                format_app_datetime(subscription_expires_at)
                if subscription_expires_at is not None
                else str(account_data.get("subscription_expires_at", ""))
            ),
            disabled=True,
        )
        st.text_input(
            f"Next Renewal ({get_app_timezone_name()})",
            value=(
                format_app_datetime(next_renewal_at)
                if next_renewal_at is not None
                else str(account_data.get("next_renewal_at", ""))
            ),
            disabled=True,
        )

    if fetched_at is not None:
        st.caption(
            f"Last account refresh: {format_app_datetime(fetched_at)} {get_app_timezone_name()}"
        )

    st.markdown("---")
    st.caption("Need Streamrip credentials and paths too?")
    if st.button("Open Streamrip Settings Tab", key="qobuz_open_streamrip_tab"):
        st.session_state.main_tab_selection_pending = "Streamrip Settings"
        st.rerun()

    return streamrip_settings, streamrip_settings_error
