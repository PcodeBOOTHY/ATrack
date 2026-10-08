import pandas as pd
import streamlit as st

from core.assessment import TYPE_LABELS
from core.difficulty import DifficultyError, effective_difficulty
from services import config, db
from services.claude_client import SUPPORTED_EXTENSIONS, UnsupportedFileError, UploadedDoc
from services.difficulty_rater import DifficultyRater, ItemContext, save_uploads
from ui import rank

st.title("🧪 Experimental Rank")
st.caption("**Experimental: AI-estimated difficulty.** A separate rating that never affects your standard rank. "
           "Opponents are rated 700 + 80 × difficulty + 10 × weight, so harder work is worth more. "
           "Only items with a rated file count here.")

if note := st.session_state.pop("exp_saved", None):
    st.success(note)

with db.open_db(config.db_path()) as conn:
    rank.summary(conn, "experimental", "🧪 Experimental: AI-estimated difficulty")
    items = [r for r in db.list_items(conn) if r["status"] == "pending"]
    rated = db.latest_files(conn)

rate_tab, rated_tab, history_tab = st.tabs(["Rate an assignment", f"Rated items ({len(rated)})", "Rank history"])

# --- rate -------------------------------------------------------------------

with rate_tab:
    if not items:
        st.info("No pending items. Import a syllabus first.")
    else:
        rated_ids = {r["item_id"] for r in rated}
        choice = st.selectbox(
            "Item", items, index=None, placeholder="Choose a pending item",
            format_func=lambda r: f"{r['course_code']} · {r['title']}" + ("  (already rated)" if r["id"] in rated_ids else ""),
        )
        uploads = st.file_uploader(
            "Assignment, lab, project or exam outline", accept_multiple_files=True,
            type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
            help="The actual assignment file (PDF, Word, screenshot or text), not the syllabus.",
        )
        if choice is not None and choice["id"] in rated_ids:
            st.caption("Rating again replaces the current difficulty for this item.")
        if st.button("Rate difficulty", type="primary", disabled=choice is None or not uploads):
            if not config.has_api_key():
                st.error("ANTHROPIC_API_KEY is not set. Add it to .env and restart.")
            else:
                files = [UploadedDoc(f.name, f.getvalue()) for f in uploads]
                context = ItemContext(choice["title"], choice["type"], choice["course_code"], choice["weight_percent"])
                try:
                    with st.spinner("Claude is reading the assignment…"):
                        result = DifficultyRater().rate(files, context)
                except (UnsupportedFileError, DifficultyError) as exc:
                    st.error(str(exc))
                else:
                    path = save_uploads(choice["id"], files)
                    with db.open_db(config.db_path()) as conn:
                        db.add_assignment_file(
                            conn, choice["id"], path, ai_difficulty=result.difficulty,
                            ai_hours=result.estimated_hours, ai_problem_count=result.problem_count,
                            ai_topics=result.topics, ai_justification=result.justification,
                        )
                    st.session_state["exp_saved"] = (
                        f"**{choice['title']}** rated **{result.difficulty}/10** · about "
                        f"{result.estimated_hours:g} h. {result.justification}")
                    st.rerun()

# --- rated items and overrides -----------------------------------------------

with rated_tab:
    if not rated:
        st.caption("No rated items yet.")
    else:
        rows = []
        for r in rated:
            used, overridden = effective_difficulty(r["ai_difficulty"], r["user_override_difficulty"])
            rows.append({
                "Item": r["title"], "Course": r["course_code"], "Type": TYPE_LABELS[r["type"]],
                "AI": r["ai_difficulty"], "Yours": r["user_override_difficulty"],
                "Used": f"{used}{' ✋' if overridden else ''}", "Hours": r["ai_hours"],
                "Problems": r["ai_problem_count"], "Topics": ", ".join(r["ai_topics"]),
                "Status": "Rated in a match" if r["has_match"] else r["status"].capitalize(),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Hours": st.column_config.NumberColumn(format="%.1f")})
        st.caption("✋ = your override. Overrides are flagged in match history.")

        st.markdown("**Details and override**")
        pick = st.selectbox("Rated item", rated, format_func=lambda r: f"{r['course_code']} · {r['title']}")
        with st.container(border=True):
            st.markdown(f"**AI difficulty: {pick['ai_difficulty']}/10** · ~{pick['ai_hours']:g} h"
                        + (f" · {pick['ai_problem_count']} problems" if pick["ai_problem_count"] is not None else ""))
            st.write(pick["ai_justification"])
            if pick["ai_topics"]:
                st.caption("Topics: " + ", ".join(pick["ai_topics"]))
            if pick["has_match"] or pick["status"] != "pending":
                st.info("This item is already finished. Its experimental result is final, so the "
                        "difficulty can't be changed.")
            else:
                with st.form(f"override_{pick['id']}"):
                    use_ai = st.toggle("Use the AI rating", value=pick["user_override_difficulty"] is None)
                    value = st.slider("Your difficulty", 1, 10,
                                      value=pick["user_override_difficulty"] or pick["ai_difficulty"])
                    if st.form_submit_button("Save"):
                        with db.open_db(config.db_path()) as conn:
                            db.set_difficulty_override(conn, pick["id"], None if use_ai else value)
                        st.session_state["exp_saved"] = (
                            f"**{pick['title']}** now uses the AI rating ({pick['ai_difficulty']})." if use_ai
                            else f"**{pick['title']}** difficulty set to {value} (your override).")
                        st.rerun()

# --- rank history -------------------------------------------------------------

with history_tab:
    with db.open_db(config.db_path()) as conn:
        rank.full_panel(conn, "experimental")
