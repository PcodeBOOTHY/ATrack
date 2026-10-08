"""Rank panels shared by the Rank page (and the Experimental page in Phase 5)."""

import altair as alt
import pandas as pd
import streamlit as st

from core.elo import PLACEMENT_MATCHES, START_RATING
from core.tiers import TIERS, next_tier, progress_to_next, tier_for
from core.timeutil import LOCAL_TZ, parse_utc_iso
from services import rating

RESULT_LABELS = {1.0: "Win", 0.5: "Half", 0.0: "Loss"}


def summary(conn, mode: str, label: str) -> None:
    """Rating, tier and progress for one mode (compact, for the top of the Rank page)."""
    value, played = rating.current_rating(conn, mode)
    tier = tier_for(value)
    with st.container(border=True):
        st.caption(label)
        left, right = st.columns([1, 2], vertical_alignment="center")
        left.metric("Rating", value, help=f"{played} matches played")
        right.markdown(f"<span style='font-size:28px'>{tier.badge}</span> "
                       f"<b style='font-size:20px;color:{tier.color}'>{tier.name}</b>", unsafe_allow_html=True)
        fraction, needed = progress_to_next(value)
        upcoming = next_tier(value)
        right.progress(fraction, text=f"{needed} points to {upcoming.name}" if upcoming else "Top tier")
        notes = [f"🔥 On-time streak: {rating.streak(conn, mode)}"]
        if played < PLACEMENT_MATCHES:
            notes.append(f"Placement: {played}/{PLACEMENT_MATCHES} matches (K = 40)")
        st.caption(" · ".join(notes))


def tier_ladder(current: int) -> None:
    current_tier = tier_for(current)
    rows = []
    for i, t in enumerate(TIERS):
        upper = TIERS[i + 1].min_rating - 1 if i + 1 < len(TIERS) else None
        if t.min_rating is None:
            span = f"below {TIERS[1].min_rating}"
        elif upper is None:
            span = f"{t.min_rating}+"
        else:
            span = f"{t.min_rating} – {upper}"
        rows.append({"": "👉" if t == current_tier else "", "Tier": f"{t.badge} {t.name}", "Rating": span})
    st.dataframe(pd.DataFrame(rows[::-1]), hide_index=True, width="stretch")


def rating_chart(history: list[dict]) -> None:
    if not history:
        st.caption("Your rating chart appears after your first completed item.")
        return
    points = [{"Match": 0, "Rating": START_RATING, "When": "Start", "Item": "", "Change": ""}]
    for n, m in enumerate(history, start=1):
        points.append({
            "Match": n, "Rating": m["rating_after"],
            "When": parse_utc_iso(m["created_at"]).astimezone(LOCAL_TZ).strftime("%b %d, %I:%M %p"),
            "Item": f"{m['course_code']} · {m['title']}", "Change": f"{m['delta']:+d}",
        })
    df = pd.DataFrame(points)
    lo, hi = df["Rating"].min() - 60, df["Rating"].max() + 60
    floors = pd.DataFrame([{"Rating": t.min_rating, "Tier": t.name} for t in TIERS
                           if t.min_rating is not None and lo <= t.min_rating <= hi])
    y = alt.Y("Rating:Q", scale=alt.Scale(domain=[lo, hi], zero=False), title=None)
    x = alt.X("Match:Q", title="Match", axis=alt.Axis(tickMinStep=1, grid=False))
    hover = alt.selection_point(fields=["Match"], nearest=True, on="pointerover", empty=False)

    line = alt.Chart(df).mark_line(strokeWidth=2, color="#4C78A8").encode(x=x, y=y)
    dots = alt.Chart(df).mark_circle(size=70, color="#4C78A8").encode(
        x=x, y=y, opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=["When", "Item", "Change", "Rating"],
    ).add_params(hover)
    layers = [line, dots]
    if not floors.empty:
        rules = alt.Chart(floors).mark_rule(strokeDash=[4, 4], color="#999999", opacity=0.6).encode(y="Rating:Q")
        labels = alt.Chart(floors).mark_text(align="left", dx=4, dy=-6, color="#888888", fontSize=11).encode(
            y="Rating:Q", x=alt.value(0), text="Tier")
        layers = [rules, labels, *layers]
    st.altair_chart(alt.layer(*layers).properties(height=280), width="stretch")


def history_table(history: list[dict], experimental: bool = False) -> None:
    if not history:
        st.caption("No matches yet.")
        return
    rows = []
    for m in reversed(history):
        row = {
            "Date": parse_utc_iso(m["created_at"]).astimezone(LOCAL_TZ).strftime("%b %d, %I:%M %p"),
            "Item": m["title"], "Course": m["course_code"],
            "Result": "Forfeit" if m["completed_at"] is None else RESULT_LABELS[m["score"]],
            "Opponent": round(m["opponent_rating"]), "Expected": m["expected"],
            "Bonus": f"×{m['multiplier']:.2f}" if m["multiplier"] > 1 else "",
            "K": m["k"], "Change": m["delta"], "Rating": m["rating_after"],
        }
        if experimental:
            row["Difficulty"] = f"{m['difficulty_used']}{' ✋' if m['difficulty_overridden'] else ''}"
        rows.append(row)
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={
            "Expected": st.column_config.NumberColumn(format="%.2f", help="Expected score E"),
            "Change": st.column_config.NumberColumn(format="%+d"),
        },
    )


def full_panel(conn, mode: str) -> None:
    value, _ = rating.current_rating(conn, mode)
    hist = rating.history(conn, mode)
    chart_col, ladder_col = st.columns([2, 1])
    with chart_col:
        st.markdown("**Rating over time**")
        rating_chart(hist)
    with ladder_col:
        st.markdown("**Tier ladder**")
        tier_ladder(value)
    st.markdown("**Match history**")
    history_table(hist, experimental=(mode == "experimental"))
    problems = rating.check_history(conn, mode)
    if problems:
        st.error("Rating history doesn't replay cleanly:\n\n" + "\n".join(f"- {p}" for p in problems))
