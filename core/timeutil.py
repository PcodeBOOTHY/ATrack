"""Time handling: store UTC, display America/Regina (UTC-6 all year, no DST).

Timestamps are stored in SQLite as ISO 8601 UTC strings like "2026-01-16T05:59:00Z".
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Regina")

# An item with a due date but no time is due at the end of that local day.
ALL_DAY_DUE_TIME = time(23, 59)

_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(dt: datetime) -> str:
    """Convert an aware datetime to the stored UTC string. Naive datetimes are rejected."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(timezone.utc).strftime(_UTC_FORMAT)


def parse_utc_iso(value: str) -> datetime:
    """Parse a stored UTC string back into an aware UTC datetime."""
    return datetime.strptime(value, _UTC_FORMAT).replace(tzinfo=timezone.utc)


def local_due_to_utc(due_date: date, due_time: time | None) -> tuple[str, bool]:
    """Turn a local due date (and optional time) into (utc_iso, all_day).

    A missing time means the item is all-day and due at 23:59 local time.
    """
    all_day = due_time is None
    local_dt = datetime.combine(due_date, ALL_DAY_DUE_TIME if all_day else due_time, LOCAL_TZ)
    return to_utc_iso(local_dt), all_day


def utc_iso_to_local(value: str) -> datetime:
    return parse_utc_iso(value).astimezone(LOCAL_TZ)


def format_local(value: str | None, all_day: bool = False) -> str:
    """Human-readable local time for display, e.g. "Fri Jan 16, 2026 11:59 PM"."""
    if value is None:
        return "TBD"
    local = utc_iso_to_local(value)
    if all_day:
        return local.strftime("%a %b %d, %Y")
    return local.strftime("%a %b %d, %Y %I:%M %p")
