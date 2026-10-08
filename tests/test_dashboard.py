from datetime import datetime, timedelta, timezone

import pytest

from core.dashboard import (
    build_items, completed, dated, filter_items, group_by, relative_due, sort_by_priority, this_week,
)
from core.timeutil import to_utc_iso

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)


def _row(id, title, type="assignment", weight=5.0, due_in_days=3.0, status="pending",
         override=None, course_id=1, completed_days_ago=None):
    return {
        "id": id, "title": title, "type": type, "course_id": course_id,
        "course_code": f"C{course_id}", "course_color": "#123456", "weight_percent": weight,
        "due_at": None if due_in_days is None else to_utc_iso(NOW + timedelta(days=due_in_days)),
        "all_day": 0, "status": status, "priority_override": override,
        "completed_at": None if completed_days_ago is None
        else to_utc_iso(NOW - timedelta(days=completed_days_ago)),
    }


def _items(*rows):
    return build_items(rows, NOW)


def test_scores_only_pending_dated_items():
    items = _items(_row(1, "A"), _row(2, "TBD", due_in_days=None),
                   _row(3, "Done", status="completed", completed_days_ago=1))
    assert items[0].score is not None and items[0].label is not None
    assert items[1].score is None and items[1].is_tbd
    assert items[2].score is None


def test_priority_sort_puts_heavy_and_urgent_first():
    items = _items(
        _row(1, "Quiz far", type="quiz", weight=2, due_in_days=20),
        _row(2, "Final soon", type="final_exam", weight=40, due_in_days=2),
        _row(3, "A1 tomorrow", weight=5, due_in_days=1),
    )
    assert [i.title for i in sort_by_priority(items)] == ["Final soon", "A1 tomorrow", "Quiz far"]


def test_override_moves_item_up():
    items = _items(
        _row(1, "Final", type="final_exam", weight=40, due_in_days=2),
        _row(2, "Quiz", type="quiz", weight=2, due_in_days=20, override="high"),
    )
    ordered = sort_by_priority(items)
    assert {i.label for i in ordered} == {"high"}  # quiz scores low but is overridden
    assert [i.title for i in ordered] == ["Final", "Quiz"]  # same label -> higher score first


def test_override_down_to_low():
    items = _items(_row(1, "Final", type="final_exam", weight=40, due_in_days=2, override="low"),
                   _row(2, "Mid", type="midterm", weight=25, due_in_days=1))
    assert [i.title for i in sort_by_priority(items)] == ["Mid", "Final"]


def test_filters_combine_and_empty_means_all():
    items = _items(_row(1, "a", course_id=1), _row(2, "b", course_id=2, type="lab"),
                   _row(3, "c", course_id=2, status="excused"))
    assert len(filter_items(items)) == 3
    assert [i.id for i in filter_items(items, course_ids=[2])] == [2, 3]
    assert [i.id for i in filter_items(items, course_ids=[2], statuses=["pending"])] == [2]
    assert [i.id for i in filter_items(items, types=["lab"])] == [2]


def test_dated_drops_tbd():
    items = _items(_row(1, "a"), _row(2, "b", due_in_days=None))
    assert [i.id for i in dated(items)] == [1]


def test_this_week_includes_overdue_excludes_far_and_done():
    items = _items(
        _row(1, "overdue", due_in_days=-2), _row(2, "in 6d", due_in_days=6),
        _row(3, "in 7d exactly", due_in_days=7), _row(4, "in 8d", due_in_days=8),
        _row(5, "done", due_in_days=1, status="completed", completed_days_ago=0),
        _row(6, "tbd", due_in_days=None),
    )
    assert [i.title for i in this_week(items, NOW)] == ["overdue", "in 6d", "in 7d exactly"]


def test_completed_newest_first():
    items = _items(_row(1, "old", status="completed", completed_days_ago=5),
                   _row(2, "new", status="completed", completed_days_ago=1), _row(3, "pending"))
    assert [i.title for i in completed(items)] == ["new", "old"]


def test_group_by_keeps_order():
    items = sort_by_priority(_items(_row(1, "a", type="lab"), _row(2, "b", type="quiz"),
                                    _row(3, "c", type="lab", weight=30)))
    groups = group_by(items, lambda i: i.type)
    assert list(groups["lab"]) == [i for i in items if i.type == "lab"]


def test_overdue_flag():
    item = _items(_row(1, "a", due_in_days=-0.1))[0]
    assert item.is_overdue(NOW)
    assert item.label is not None and item.score >= 0.35  # U = 1 when overdue


@pytest.mark.parametrize("delta,text", [
    (timedelta(days=3), "in 3 days"),
    (timedelta(hours=5), "in 5 h"),
    (timedelta(minutes=20), "in 20 min"),
    (timedelta(hours=-30), "overdue 30 h"),
    (timedelta(days=-4), "overdue 4 days"),
])
def test_relative_due(delta, text):
    assert relative_due(NOW + delta, NOW) == text


def test_relative_due_tbd():
    assert relative_due(None, NOW) == "TBD"
