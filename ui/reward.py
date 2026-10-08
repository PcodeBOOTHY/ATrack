"""Completion dialog and reward screen (SPEC section 4.4)."""

from datetime import datetime, time

import streamlit as st
import streamlit.components.v1 as components

from core.elo import HALF, WIN, actual_score, earliness_multiplier
from core.rewards import pick_message
from core.tiers import next_tier, progress_to_next
from core.timeutil import LOCAL_TZ, now_utc, parse_utc_iso
from services import config, db, rating
from services.rating import CompletionResult, MatchOutcome, RatingError

REWARD_KEY = "reward"

_CONFETTI = """
<canvas id="c" style="position:fixed;inset:0;width:100%;height:100%;pointer-events:none"></canvas>
<div style="font:600 {size}px sans-serif;text-align:center;padding-top:{pad}px">{text}</div>
<script>
const c = document.getElementById('c'), x = c.getContext('2d');
c.width = innerWidth; c.height = innerHeight;
const colors = ['#4C78A8','#F58518','#54A24B','#E45756','#EECA3B','#B279A2'];
const bits = Array.from({length: {count}}, () => ({
  x: c.width / 2, y: c.height * 0.9, r: 3 + Math.random() * 4,
  vx: (Math.random() - 0.5) * 14, vy: -8 - Math.random() * 10,
  a: Math.random() * 6, va: (Math.random() - 0.5) * 0.4,
  col: colors[Math.floor(Math.random() * colors.length)]
}));
let t = 0;
(function frame() {
  x.clearRect(0, 0, c.width, c.height);
  for (const b of bits) {
    b.x += b.vx; b.y += b.vy; b.vy += 0.35; b.vx *= 0.99; b.a += b.va;
    x.save(); x.translate(b.x, b.y); x.rotate(b.a); x.fillStyle = b.col;
    x.fillRect(-b.r, -b.r / 2, b.r * 2, b.r); x.restore();
  }
  if (t++ < 160) requestAnimationFrame(frame); else x.clearRect(0, 0, c.width, c.height);
})();
</script>
"""


def _confetti(text: str, big: bool = False) -> None:
    html = (_CONFETTI.replace("{size}", "44" if big else "30").replace("{pad}", "40" if big else "30")
            .replace("{count}", "220" if big else "120").replace("{text}", text))
    components.html(html, height=150 if big else 110)


def _result_text(score: float, multiplier: float) -> str:
    if score == WIN:
        return f"On time ✅ · early bonus ×{multiplier:.2f}" if multiplier > 1 else "On time ✅"
    if score == HALF:
        return "Up to 24 h late · half credit"
    return "More than 24 h late · counts as a loss"


def _outcome_block(o: MatchOutcome, label: str) -> None:
    left, right = st.columns([1, 2], vertical_alignment="center")
    left.metric(label, o.rating_after, f"{o.delta:+d}")
    fraction, needed = progress_to_next(o.rating_after)
    upcoming = next_tier(o.rating_after)
    right.markdown(f"{o.tier_after.badge} **{o.tier_after.name}**")
    if upcoming:
        right.progress(fraction, text=f"{needed} points to {upcoming.badge} {upcoming.name}")
    else:
        right.progress(1.0, text="Top tier reached")


@st.dialog("Complete item")
def complete_dialog(item_id: int, title: str, due_at: str) -> None:
    due = parse_utc_iso(due_at)
    now = now_utc()
    st.markdown(f"**{title}**  \nDue {due.astimezone(LOCAL_TZ).strftime('%a %b %d, %I:%M %p')}")
    when = st.radio("When did you finish?", ["Just now", "Earlier"], horizontal=True)
    completed_at = now
    if when == "Earlier":
        local_now = now.astimezone(LOCAL_TZ)
        c1, c2 = st.columns(2)
        day = c1.date_input("Date", value=local_now.date(), max_value=local_now.date(), format="YYYY-MM-DD")
        clock = c2.time_input("Time", value=time(local_now.hour, local_now.minute), step=300)
        completed_at = datetime.combine(day, clock, LOCAL_TZ).astimezone(now.tzinfo)

    score = actual_score(due, completed_at)
    preview = _result_text(score, earliness_multiplier(due, completed_at, score))
    days_early = (due - completed_at).total_seconds() / 86400
    if days_early > 0:
        preview += f" ({days_early:.1f} days early; bonus maxes out at 7)"
    st.caption(preview)

    if st.button("Mark complete", type="primary", width="stretch"):
        try:
            with db.open_db(config.db_path()) as conn:
                result = rating.complete_item(conn, item_id, completed_at, now_utc())
        except RatingError as exc:
            st.error(str(exc))
        else:
            st.session_state[REWARD_KEY] = result
            st.rerun()


def _reward_body(res: CompletionResult) -> None:
    s = res.standard
    change = s.tier_change
    # The dialog reruns when its buttons are clicked; celebrate only the first time
    first_view = st.session_state.get("celebrated") != s.match_id
    st.session_state["celebrated"] = s.match_id
    if change > 0:
        if first_view:
            st.balloons()
            _confetti("RANK UP!", big=True)
        st.markdown(
            f"<div style='text-align:center'><div style='font-size:72px'>{s.tier_after.badge}</div>"
            f"<div style='font-size:14px;letter-spacing:.2em;opacity:.7'>NEW RANK</div>"
            f"<div style='font-size:34px;font-weight:700;color:{s.tier_after.color}'>{s.tier_after.name}</div></div>",
            unsafe_allow_html=True,
        )
    elif s.score > 0 and change == 0 and first_view:
        st.balloons()
        _confetti(f"{s.delta:+d}")

    st.markdown(f"### {res.title}")
    st.caption(_result_text(s.score, s.multiplier))
    _outcome_block(s, "Rating")
    if res.experimental:
        e = res.experimental
        st.caption(f"🧪 Experimental: {e.rating_before} → {e.rating_after} ({e.delta:+d}) · {e.tier_after.name}")

    st.markdown(f"🔥 On-time streak: **{res.streak}**")
    if change < 0:
        st.info(f"You moved to {s.tier_after.badge} {s.tier_after.name}. "
                + pick_message(s.match_id, s.score, demoted=True))
    else:
        st.success(pick_message(s.match_id, s.score))

    undo, close = st.columns(2)
    if undo.button("Undo (10 min)", width="stretch"):
        try:
            with db.open_db(config.db_path()) as conn:
                rating.undo_completion(conn, res.item_id, now_utc())
        except RatingError as exc:
            st.error(str(exc))
        else:
            st.session_state["dashboard_saved"] = f"Undid **{res.title}**. Rating restored."
            st.rerun()
    if close.button("Close", type="primary", width="stretch"):
        st.rerun()


@st.dialog("🎉 Item complete", width="medium")
def _reward_dialog(res: CompletionResult) -> None:
    _reward_body(res)


@st.dialog("⬆️ Rank up!", width="large")
def _rank_up_dialog(res: CompletionResult) -> None:
    _reward_body(res)


@st.dialog("Item complete", width="medium")
def _quiet_dialog(res: CompletionResult) -> None:
    _reward_body(res)


def show_pending_reward() -> None:
    """Open the reward screen if a completion just happened (call once per run)."""
    res = st.session_state.pop(REWARD_KEY, None)
    if res is None:
        return
    change = res.standard.tier_change
    if change > 0:
        _rank_up_dialog(res)
    elif change < 0 or res.standard.score == 0:
        _quiet_dialog(res)
    else:
        _reward_dialog(res)
