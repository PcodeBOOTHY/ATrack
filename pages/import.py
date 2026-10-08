import pandas as pd
import streamlit as st

from core.assessment import ITEM_TYPES
from core.extraction import (
    LOW_CONFIDENCE, ExtractionError, SyllabusExtraction, is_low_confidence,
    rows_to_new_items, to_review_rows, total_weight,
)
from services import config, db
from services.syllabus_parser import (
    SUPPORTED_EXTENSIONS, SyllabusParser, UnsupportedFileError, UploadedDoc,
)

RESULT_KEY = "import_result"
COURSE_FIELDS = ("code", "name", "section", "instructor", "term")

st.title("📥 Import Syllabus")

if not config.has_api_key():
    st.error("ANTHROPIC_API_KEY is not set. Add it to your .env file and restart the app.")
    st.stop()


def _reset_review() -> None:
    for key in list(st.session_state):
        if key == RESULT_KEY or key.startswith(("course_", "editor_")):
            del st.session_state[key]


# --- step 1: upload ---------------------------------------------------------

if RESULT_KEY not in st.session_state:
    if saved := st.session_state.pop("import_saved", None):
        st.success("Saved. " + " · ".join(saved))
        st.page_link("pages/tbd.py", label="Items without dates are waiting in TBD", icon="❓")
    st.write("Upload one or more syllabi, or paste the text. Claude extracts every graded item, "
             "then you review it before anything is saved.")
    uploads = st.file_uploader(
        "Syllabus files",
        type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
    )
    pasted = st.text_area("Or paste syllabus text", height=150)

    if st.button("Extract assessments", type="primary"):
        files = [UploadedDoc(f.name, f.getvalue()) for f in uploads or []]
        try:
            with st.spinner(f"Reading syllabus with {config.anthropic_model()}… this can take a minute."):
                result = SyllabusParser().extract(files, pasted)
        except (UnsupportedFileError, ExtractionError) as exc:
            st.error(str(exc))
        else:
            if not result.courses:
                st.warning("No graded assessments were found. Check the file is a syllabus.")
            else:
                st.session_state[RESULT_KEY] = result.model_dump(mode="json")
                st.rerun()
    st.stop()


# --- step 2: review ---------------------------------------------------------

extraction = SyllabusExtraction.model_validate(st.session_state[RESULT_KEY])
st.subheader("Review before saving")
st.caption(
    f"Nothing is saved until you click **Confirm**. Rows marked ⚠️ have confidence below "
    f"{LOW_CONFIDENCE:.0%}; check them against the source quote. Items without a due date go to TBD. "
    "Untick **Save** to skip a row, or add rows at the bottom."
)

COLUMN_CONFIG = {
    "include": st.column_config.CheckboxColumn("Save", default=True, width="small"),
    "flag": st.column_config.TextColumn("", disabled=True, width="small"),
    "title": st.column_config.TextColumn("Title", required=True),
    "type": st.column_config.SelectboxColumn("Type", options=list(ITEM_TYPES), required=True),
    "weight_percent": st.column_config.NumberColumn("Weight %", min_value=0, max_value=100, format="%.1f"),
    "due_date": st.column_config.DateColumn("Due date", format="YYYY-MM-DD"),
    "due_time": st.column_config.TimeColumn("Due time", format="HH:mm"),
    "location": st.column_config.TextColumn("Location"),
    "notes": st.column_config.TextColumn("Notes"),
    "confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=1, format="%.2f"),
    "source_quote": st.column_config.TextColumn("Source quote", disabled=True, width="large"),
}

edited: list[tuple[dict, list[dict]]] = []
for i, course_ext in enumerate(extraction.courses):
    course = course_ext.course
    with st.container(border=True):
        cols = st.columns([1, 2, 1, 2, 1.5])
        info = {
            field: col.text_input(field.capitalize(), value=getattr(course, field) or "", key=f"course_{i}_{field}")
            for field, col in zip(COURSE_FIELDS, cols)
        }

        rows = to_review_rows(course_ext)
        flagged = sum(is_low_confidence(r["confidence"]) for r in rows)
        tbd = sum(r["due_date"] is None for r in rows)
        df = pd.DataFrame(rows, columns=list(COLUMN_CONFIG))
        df["due_date"] = pd.to_datetime(df["due_date"]).dt.date
        result = st.data_editor(
            df,
            column_config=COLUMN_CONFIG,
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            key=f"editor_{i}",
        )
        edited_rows = result.to_dict("records")

        weight = total_weight(edited_rows)
        summary = f"{len(rows)} items found · {tbd} without a date (→ TBD) · weights add to {weight:.1f}%"
        if flagged:
            summary += f" · ⚠️ {flagged} low-confidence"
        st.caption(summary)
        if weight and abs(weight - 100) > 0.5:
            st.warning(f"Weights add to {weight:.1f}%, not 100%. Check for missing or split items.")

    edited.append(({k: (v.strip() or None) for k, v in info.items()}, edited_rows))

left, right = st.columns(2)
if left.button("Confirm and save", type="primary", width="stretch"):
    errors: list[str] = []
    to_save = []
    for n, (info, rows) in enumerate(edited, start=1):
        if not info["code"]:
            errors.append(f"Course {n}: course code is required.")
        items, row_errors = rows_to_new_items(rows)
        errors += [f"{info['code'] or f'Course {n}'} – {e}" for e in row_errors]
        to_save.append((info, items))

    if errors:
        st.error("Fix these before saving:\n\n" + "\n".join(f"- {e}" for e in errors))
    else:
        messages = []
        with db.open_db(config.db_path()) as conn:
            for info, items in to_save:
                _, added, skipped = db.save_import(conn, info, items)
                msg = f"**{info['code']}**: {added} saved"
                if skipped:
                    msg += f", {skipped} already existed"
                messages.append(msg)
        _reset_review()
        st.session_state["import_saved"] = messages
        st.rerun()

if right.button("Discard", width="stretch"):
    _reset_review()
    st.rerun()
