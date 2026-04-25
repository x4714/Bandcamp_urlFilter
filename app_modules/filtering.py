from __future__ import annotations

from datetime import date

from app_modules.debug_logging import emit_debug
from logic.bandcamp_filter import LogEntry, filter_entries


def _filtering_debug(message: str) -> None:
    emit_debug("filtering", message)


def _new_date_filter_stats() -> dict[str, int | bool]:
    return {
        "date_filter_active": False,
        "date_filtered_out": 0,
        "missing_release_date": 0,
    }


def get_download_link(data_list: list[dict]) -> str:
    _filtering_debug(f"Building download link text from {len(data_list)} row(s).")
    qobuz_urls = [d["qobuz_url"] for d in data_list if d.get("qobuz_url")]
    _filtering_debug(f"Extracted {len(qobuz_urls)} qobuz URL(s) for download text.")
    return "\n".join(qobuz_urls)


def validate_filters(
    min_tracks: int | None,
    max_tracks: int | None,
    min_duration: int | None,
    max_duration: int | None,
    start_date: date | None,
    end_date: date | None,
) -> list[str]:
    _filtering_debug("Validating filter inputs.")
    errors: list[str] = []
    if min_tracks is not None and max_tracks is not None and min_tracks > max_tracks:
        errors.append("Min Tracks must be less than or equal to Max Tracks.")
    if min_duration is not None and max_duration is not None and min_duration > max_duration:
        errors.append("Min Duration must be less than or equal to Max Duration.")
    if start_date and end_date and start_date > end_date:
        errors.append("Start Date must be on or before End Date.")
    _filtering_debug(f"Filter validation complete with {len(errors)} error(s).")
    return errors


def build_filtered_entries(
    lines: list[str],
    filter_config: dict[str, object],
    start_date: date | None,
    end_date: date | None,
) -> tuple[list[LogEntry], dict[str, int | bool]]:
    _filtering_debug(
        f"Building filtered entries from {len(lines)} line(s). "
        f"date_filter_active={bool(start_date or end_date)}"
    )
    filtered_entries = filter_entries(lines, filter_config)
    _filtering_debug(f"Base filtering returned {len(filtered_entries)} entry(ies).")
    date_filter_stats = _new_date_filter_stats()

    if start_date or end_date:
        date_filter_stats["date_filter_active"] = True
        date_filtered_entries: list[LogEntry] = []
        for entry in filtered_entries:
            if not entry.release_date:
                date_filter_stats["missing_release_date"] += 1
                date_filtered_entries.append(entry)
                continue

            start_ok = not start_date or entry.release_date >= start_date
            end_ok = not end_date or entry.release_date <= end_date
            if start_ok and end_ok:
                date_filtered_entries.append(entry)
            else:
                date_filter_stats["date_filtered_out"] += 1

        filtered_entries = date_filtered_entries
        _filtering_debug(
            "Date filtering reduced entries to "
            f"{len(filtered_entries)} (date_filtered_out={date_filter_stats['date_filtered_out']}, "
            f"missing_release_date={date_filter_stats['missing_release_date']})."
        )

    deduped_entries: list[LogEntry] = []
    seen_urls: set[str] = set()
    for entry in filtered_entries:
        key = entry.url.strip().lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        deduped_entries.append(entry)

    _filtering_debug(f"Deduped entries count: {len(deduped_entries)}.")
    return deduped_entries, date_filter_stats
