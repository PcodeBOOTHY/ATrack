from datetime import date, datetime, time, timezone

import pytest

from core.timeutil import (
    format_local, local_due_to_utc, parse_utc_iso, to_utc_iso, utc_iso_to_local,
)


def test_timed_due_converts_to_utc():
    # Regina is UTC-6, so 14:30 local is 20:30 UTC
    assert local_due_to_utc(date(2026, 1, 15), time(14, 30)) == ("2026-01-15T20:30:00Z", False)


def test_all_day_due_is_2359_local():
    # 23:59 local on Jan 15 is 05:59 UTC on Jan 16
    assert local_due_to_utc(date(2026, 1, 15), None) == ("2026-01-16T05:59:00Z", True)


def test_no_dst_offset_is_same_in_summer_and_winter():
    winter, _ = local_due_to_utc(date(2026, 1, 15), time(12, 0))
    summer, _ = local_due_to_utc(date(2026, 7, 15), time(12, 0))
    assert winter.endswith("T18:00:00Z")
    assert summer.endswith("T18:00:00Z")


def test_round_trip():
    dt = datetime(2026, 3, 8, 9, 15, tzinfo=timezone.utc)
    assert parse_utc_iso(to_utc_iso(dt)) == dt


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        to_utc_iso(datetime(2026, 1, 1, 12, 0))


def test_utc_to_local():
    local = utc_iso_to_local("2026-01-16T05:59:00Z")
    assert (local.date(), local.hour, local.minute) == (date(2026, 1, 15), 23, 59)


def test_format_local():
    assert format_local(None) == "TBD"
    assert format_local("2026-01-16T05:59:00Z", all_day=True) == "Thu Jan 15, 2026"
    assert format_local("2026-01-15T20:30:00Z") == "Thu Jan 15, 2026 02:30 PM"
