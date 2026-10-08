"""Item tables shared by the dashboard views."""

from datetime import datetime

import pandas as pd
import streamlit as st

from core.assessment import TYPE_LABELS
from core.dashboard import DashboardItem, relative_due
from core.timeutil import LOCAL_TZ

LABEL_BADGES = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}
STATUS_LABELS = {"pending": "Pending", "completed": "✅ Completed", "forfeited": "❌ Forfeited",
                 "excused": "🟦 Excused"}


def _due_text(item: DashboardItem) -> str:
    if item.due_at is None:
        return "TBD"
    local = item.due_at.astimezone(LOCAL_TZ)
    return local.strftime("%a %b %d") if item.all_day else local.strftime("%a %b %d, %I:%M %p")


def item_table(items: list[DashboardItem], now: datetime, *, completed: bool = False, key: str) -> None:
    if not items:
        st.caption("Nothing here.")
        return
    rows = []
    for i in items:
        badge = LABEL_BADGES.get(i.label, "")
        if i.priority_override and badge:
            badge += " ✋"
        row = {
            "Priority": badge,
            "Title": i.title,
            "Course": i.course_code,
            "Type": TYPE_LABELS.get(i.type, i.type),
            "Weight %": i.weight_percent,
            "Due": _due_text(i),
            "When": relative_due(i.due_at, now) if i.status == "pending" else STATUS_LABELS[i.status],
            "Score": i.score,
            "_color": i.course_color,
        }
        if completed:
            row["Completed"] = (i.completed_at.astimezone(LOCAL_TZ).strftime("%a %b %d, %I:%M %p")
                                if i.completed_at else "")
            for col in ("Priority", "When", "Score"):
                row.pop(col)
        rows.append(row)

    df = pd.DataFrame(rows)
    colors = df.pop("_color")
    styled = df.style.apply(
        lambda col: [f"background-color: {c}33; font-weight: 600" for c in colors], subset=["Course"]
    )
    if "When" in df:
        styled = styled.apply(
            lambda col: ["color: #d62728; font-weight: 600" if str(v).startswith("overdue") else ""
                         for v in col], subset=["When"],
        )
    st.dataframe(
        styled,
        hide_index=True,
        width="stretch",
        key=key,
        column_config={
            "Weight %": st.column_config.NumberColumn(format="%.1f"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f",
                                                     help="Priority score P from weight, urgency and difficulty"),
        },
    )
