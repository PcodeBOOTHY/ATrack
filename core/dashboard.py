"""Dashboard views: scoring, filtering, sorting and grouping items (SPEC section 4.3)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from core.priority import LABEL_RANK, effective_label, priority_score
from core.timeutil import parse_utc_iso

THIS_WEEK_DAYS = 7


@dataclass(frozen=True)
class DashboardItem:
    id: int
    title: str
    type: str
    course_id: int
    course_code: str
    course_color: str
    weight_percent: float | None
    due_at: datetime | None
    all_day: bool
    status: str
    priority_override: str | None
    location: str | None = None
    notes: str | None = None
    completed_at: datetime | None = None
    score: float | None = None   # only for pending items with a due date
    label: str | None = None

    @property
    def is_tbd(self) -> bool:
        return self.due_at is None

    def is_overdue(self, now: datetime) -> bool:
        return self.status == "pending" and self.due_at is not None and self.due_at <= now


def build_items(rows: Iterable[dict[str, Any]], now: datetime) -> list[DashboardItem]:
    """Turn database rows into scored DashboardItems."""
    items = []
    for r in rows:
        due = parse_utc_iso(r["due_at"]) if r.get("due_at") else None
        score = label = None
        if due is not None and r["status"] == "pending":
            score = priority_score(r["type"], r.get("weight_percent"), due, now, r.get("difficulty"))
            label = effective_label(score, r.get("priority_override"))
        items.append(DashboardItem(
            id=r["id"], title=r["title"], type=r["type"], course_id=r["course_id"],
            course_code=r["course_code"], course_color=r.get("course_color") or "#888888",
            weight_percent=r.get("weight_percent"), due_at=due, all_day=bool(r.get("all_day")),
            status=r["status"], priority_override=r.get("priority_override"),
            location=r.get("location"), notes=r.get("notes"),
            completed_at=parse_utc_iso(r["completed_at"]) if r.get("completed_at") else None,
            score=score, label=label,
        ))
    return items


def filter_items(
    items: Iterable[DashboardItem],
    course_ids: Iterable[int] | None = None,
    types: Iterable[str] | None = None,
    statuses: Iterable[str] | None = None,
) -> list[DashboardItem]:
    """Empty or None filters mean 'everything'."""
    course_ids, types, statuses = set(course_ids or ()), set(types or ()), set(statuses or ())
    return [
        i for i in items
        if (not course_ids or i.course_id in course_ids)
        and (not types or i.type in types)
        and (not statuses or i.status in statuses)
    ]


def dated(items: Iterable[DashboardItem]) -> list[DashboardItem]:
    """Dashboard views only show items with a due date; TBD items live on the TBD page."""
    return [i for i in items if not i.is_tbd]


def _due_key(item: DashboardItem) -> tuple:
    return (item.due_at is None, item.due_at or datetime.max)


def sort_by_priority(items: Iterable[DashboardItem]) -> list[DashboardItem]:
    """Label first (so overrides take effect), then score, then soonest due."""
    return sorted(items, key=lambda i: (
        -LABEL_RANK.get(i.label, -1), -(i.score or 0), *_due_key(i), i.title.lower(),
    ))


def sort_by_due(items: Iterable[DashboardItem]) -> list[DashboardItem]:
    return sorted(items, key=lambda i: (*_due_key(i), i.title.lower()))


def group_by(
    items: Iterable[DashboardItem], key: Callable[[DashboardItem], Any]
) -> dict[Any, list[DashboardItem]]:
    """Groups keep the order items arrive in, so sort first."""
    groups: dict[Any, list[DashboardItem]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return groups


def this_week(items: Iterable[DashboardItem], now: datetime) -> list[DashboardItem]:
    """Pending items that are overdue or due within the next 7 days, soonest first."""
    end = now + timedelta(days=THIS_WEEK_DAYS)
    return sort_by_due(
        i for i in items if i.status == "pending" and i.due_at is not None and i.due_at <= end
    )


def completed(items: Iterable[DashboardItem]) -> list[DashboardItem]:
    """Most recently completed first."""
    done = [i for i in items if i.status == "completed"]
    return sorted(done, key=lambda i: i.completed_at or datetime.min, reverse=True)


def relative_due(due_at: datetime | None, now: datetime) -> str:
    """'in 3 days', 'in 5 h', 'due now', 'overdue 2 days'."""
    if due_at is None:
        return "TBD"
    seconds = (due_at - now).total_seconds()
    ahead = seconds >= 0
    hours = abs(seconds) / 3600
    if hours < 1:
        text = f"{max(1, round(hours * 60))} min"
    elif hours < 48:
        text = f"{round(hours)} h"
    else:
        days = round(hours / 24)
        text = f"{days} days"
    return f"in {text}" if ahead else f"overdue {text}"
