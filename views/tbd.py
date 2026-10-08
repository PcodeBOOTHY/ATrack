import streamlit as st

from core.assessment import TYPE_LABELS
from core.dashboard import group_by
from core.timeutil import local_due_to_utc
from services import config, db

st.title("❓ TBD")
st.caption("Items with no due date yet. Set a date and they move to the dashboard. "
           "Leave the time empty for an all-day item (due 11:59 PM).")

with db.open_db(config.db_path()) as conn:
    rows = db.list_tbd_items(conn)

if saved := st.session_state.pop("tbd_saved", None):
    st.success(f"**{saved}** moved to the dashboard.")

if not rows:
    st.success("Nothing in TBD. Every item has a date. 🎉")
    st.stop()

for course_code, items in group_by(rows, lambda r: r["course_code"]).items():
    color = items[0]["course_color"]
    st.markdown(f"<h3 style='border-left: 6px solid {color}; padding-left: 10px'>{course_code}"
                f" <small style='opacity:.6'>{items[0]['course_name'] or ''}</small></h3>",
                unsafe_allow_html=True)
    for item in items:
        with st.form(f"tbd_{item['id']}", border=True):
            info, date_col, time_col, button_col = st.columns([3, 1.3, 1.1, 0.8], vertical_alignment="bottom")
            weight = f" · {item['weight_percent']:g}%" if item["weight_percent"] is not None else ""
            info.markdown(f"**{item['title']}**  \n{TYPE_LABELS[item['type']]}{weight}")
            if item["notes"]:
                info.caption(item["notes"])
            due_date = date_col.date_input("Due date", value=None, format="YYYY-MM-DD")
            due_time = time_col.time_input("Time (optional)", value=None, step=300)
            if button_col.form_submit_button("Save", type="primary", width="stretch"):
                if due_date is None:
                    st.error("Pick a due date first.")
                else:
                    due_at, all_day = local_due_to_utc(due_date, due_time)
                    with db.open_db(config.db_path()) as conn:
                        db.set_item_due(conn, item["id"], due_at, all_day)
                    st.session_state["tbd_saved"] = item["title"]
                    st.rerun()
            if item["source_quote"]:
                st.caption(f"From syllabus: “{item['source_quote']}”")
