import streamlit as st

from core.assessment import ITEM_TYPES, TYPE_LABELS
from core.dashboard import (
    build_items, completed, dated, filter_items, group_by, sort_by_priority, this_week,
)
from core.timeutil import LOCAL_TZ, local_due_to_utc, now_utc, to_utc_iso
from services import config, db, rating
from services.rating import RatingError
from ui.items import STATUS_LABELS, item_table
from ui.reward import complete_dialog

st.title("📋 Dashboard")

now = now_utc()
with db.open_db(config.db_path()) as conn:
    rows = db.list_items(conn)
    courses = db.list_courses(conn)
items = build_items(rows, now)

if not items:
    st.info("No items yet. Import a syllabus to get started.")
    st.page_link("views/import.py", label="Import a syllabus", icon="📥")
    st.stop()

if saved := st.session_state.pop("dashboard_saved", None):
    st.success(saved)

with db.open_db(config.db_path()) as conn:
    recent = rating.undoable_completion(conn, now)
if recent is not None:
    note, button = st.columns([4, 1], vertical_alignment="center")
    note.info(f"Completed **{recent['title']}** ({recent['delta']:+d}). You can undo this for 10 minutes.")
    if button.button("Undo", width="stretch"):
        try:
            with db.open_db(config.db_path()) as conn:
                rating.undo_completion(conn, recent["item_id"], now_utc())
        except RatingError as exc:
            st.error(str(exc))
        else:
            st.session_state["dashboard_saved"] = f"Undid **{recent['title']}**. Rating restored."
            st.rerun()


def _set_excused(item_id: int, excused: bool, title: str) -> None:
    try:
        with db.open_db(config.db_path()) as conn:
            rating.set_excused(conn, item_id, excused)
    except RatingError as exc:
        st.error(str(exc))
        return
    st.session_state["dashboard_saved"] = (
        f"**{title}** excused. It won't count toward your rank." if excused else f"**{title}** is pending again.")
    st.rerun()


def actions(selected, key: str) -> None:
    """Buttons for the row selected in a table."""
    if selected is None:
        return
    with st.container(border=True):
        info, b1, b2 = st.columns([3, 1, 1], vertical_alignment="center")
        info.markdown(f"**{selected.title}** · {selected.course_code}")
        if selected.status == "pending":
            if b1.button("✅ Mark complete", key=f"{key}_done", type="primary", width="stretch"):
                complete_dialog(selected.id, selected.title, to_utc_iso(selected.due_at))
            if b2.button("🟦 Excused", key=f"{key}_excuse", width="stretch",
                         help="Extension or deferral: no rating change"):
                _set_excused(selected.id, True, selected.title)
        elif selected.status == "excused":
            if b1.button("↩️ Not excused", key=f"{key}_unexcuse", width="stretch"):
                _set_excused(selected.id, False, selected.title)
        else:
            info.caption(STATUS_LABELS[selected.status])

# --- filters ----------------------------------------------------------------

course_names = {c["id"]: c["code"] for c in courses}
f1, f2, f3 = st.columns(3)
course_filter = f1.multiselect("Course", list(course_names), format_func=course_names.get,
                               placeholder="All courses")
type_filter = f2.multiselect("Type", list(ITEM_TYPES), format_func=TYPE_LABELS.get, placeholder="All types")
status_filter = f3.multiselect("Status", list(STATUS_LABELS), default=["pending"],
                               format_func=lambda s: STATUS_LABELS[s].split(" ", 1)[-1],
                               placeholder="All statuses")

scoped = filter_items(items, course_filter, type_filter)       # course + type only
visible = dated(filter_items(scoped, statuses=status_filter))  # + status, no TBD

pending = [i for i in dated(scoped) if i.status == "pending"]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Pending", len(pending))
m2.metric("Overdue", sum(i.is_overdue(now) for i in pending))
m3.metric("Due in 7 days", len(this_week(pending, now)))
m4.metric("High priority", sum(i.label == "high" for i in pending))

# --- views ------------------------------------------------------------------

by_priority, by_type, by_course, week, done = st.tabs(
    ["By Priority", "By Type", "By Course", "This Week", "Completed"]
)
ordered = sort_by_priority(visible)

st.caption("Select a row (click its left edge) to complete it or mark it excused.")
with by_priority:
    actions(item_table(ordered, now, key="t_priority"), "t_priority")

with by_type:
    groups = group_by(ordered, lambda i: i.type)
    for t in ITEM_TYPES:
        if t in groups:
            st.subheader(f"{TYPE_LABELS[t]} ({len(groups[t])})")
            actions(item_table(groups[t], now, key=f"t_type_{t}"), f"t_type_{t}")
    if not groups:
        st.caption("Nothing here.")

with by_course:
    groups = group_by(ordered, lambda i: (i.course_code, i.course_color))
    for (code, color), group in sorted(groups.items()):
        st.markdown(f"<h3 style='border-left: 6px solid {color}; padding-left: 10px'>{code} "
                    f"({len(group)})</h3>", unsafe_allow_html=True)
        actions(item_table(group, now, key=f"t_course_{code}"), f"t_course_{code}")
    if not groups:
        st.caption("Nothing here.")

with week:
    st.caption("Overdue items and everything due in the next 7 days, soonest first.")
    actions(item_table(this_week(scoped, now), now, key="t_week"), "t_week")

with done:
    item_table(completed(scoped), now, completed=True, key="t_done")

st.caption("Priority: 🔴 High (score ≥ 0.60) · 🟠 Medium (0.35–0.59) · 🟢 Low (< 0.35) · "
           "✋ = set by you. Score = 0.5 × weight + 0.35 × urgency + 0.15 × difficulty.")

# --- edit -------------------------------------------------------------------

st.divider()
with st.expander("✏️ Edit an item"):
    editable = sorted(scoped, key=lambda i: (i.course_code, i.title.lower()))
    choice = st.selectbox(
        "Item", editable, index=None, placeholder="Choose an item",
        format_func=lambda i: f"{i.course_code} · {i.title}" + (" (TBD)" if i.is_tbd else ""),
    )
    if choice is not None:
        local_due = choice.due_at.astimezone(LOCAL_TZ) if choice.due_at else None
        with st.form(f"edit_{choice.id}"):
            c1, c2 = st.columns(2)
            title = c1.text_input("Title", choice.title)
            item_type = c2.selectbox("Type", ITEM_TYPES, index=ITEM_TYPES.index(choice.type),
                                     format_func=TYPE_LABELS.get)
            c3, c4, c5 = st.columns(3)
            due_date = c3.date_input("Due date (empty = TBD)", value=local_due.date() if local_due else None,
                                     format="YYYY-MM-DD")
            due_time = c4.time_input("Time (empty = all day)",
                                     value=None if (local_due is None or choice.all_day) else local_due.time(),
                                     step=300)
            weight = c5.number_input("Weight %", min_value=0.0, max_value=100.0, step=0.5,
                                     value=choice.weight_percent)
            override_options = [None, "high", "medium", "low"]
            override = st.radio(
                "Priority", override_options, index=override_options.index(choice.priority_override),
                format_func=lambda o: "Automatic" if o is None else o.capitalize(), horizontal=True,
            )
            notes = st.text_area("Notes", choice.notes or "", height=80)
            save, delete = st.columns([3, 1])
            submitted = save.form_submit_button("Save changes", type="primary")
            confirm_delete = delete.checkbox("Confirm delete")
            deleted = delete.form_submit_button("Delete item")

        if submitted:
            if not title.strip():
                st.error("Title can't be empty.")
            else:
                due_at, all_day = local_due_to_utc(due_date, due_time) if due_date else (None, False)
                with db.open_db(config.db_path()) as conn:
                    db.update_item(conn, choice.id, title=title.strip(), type=item_type, weight_percent=weight,
                                   due_at=due_at, all_day=all_day, priority_override=override,
                                   notes=notes.strip() or None)
                st.session_state["dashboard_saved"] = f"Saved **{title.strip()}**."
                st.rerun()
        if deleted:
            if not confirm_delete:
                st.warning("Tick “Confirm delete” first.")
            else:
                try:
                    with db.open_db(config.db_path()) as conn:
                        db.delete_item(conn, choice.id)
                except db.sqlite3.IntegrityError:
                    st.error("This item has rating history and can't be deleted.")
                else:
                    st.session_state["dashboard_saved"] = f"Deleted **{choice.title}**."
                    st.rerun()
