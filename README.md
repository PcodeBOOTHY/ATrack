# Academic Weapon

A local, single-user assignment tracker. Upload course syllabi, let Claude extract every
assessment, review it, and track your work with an Elo rank from Wood to Certified Academic
Weapon. See [SPEC.md](SPEC.md) for the full design.

**Status:** Phase 2 done (syllabus import with review). Next: Phase 3 (TBD page, dashboard, priority).

## Setup

Requires Python 3.11 or newer.

```bash
git clone https://github.com/PcodeBOOTHY/ATrack.git
cd ATrack

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\Activate.ps1     # Windows PowerShell

pip install -r requirements.txt

# Configure secrets
cp .env.example .env             # Windows: copy .env.example .env
# then edit .env and set ANTHROPIC_API_KEY
```

### .env variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes, for import | (none) | Claude API key for syllabus import and difficulty rating |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-5-5` | Model used for extraction |
| `APP_DB_PATH` | No | `data/app.db` | SQLite file (relative paths resolve from the project root) |

## Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501. The database is created automatically at `data/app.db`
on first start. `data/` and `.env` are git-ignored.

## Importing a syllabus

1. Open **Import Syllabus**, upload PDF / DOCX / PNG / JPG / TXT files, or paste text.
2. Click **Extract assessments**. Claude reads the files and returns every graded item.
3. Review the table. ⚠️ marks items with confidence below 70%; compare them with the
   source quote. Edit any cell, untick **Save** to skip a row, or add rows.
4. Click **Confirm and save**. Items without a due date go to TBD.

Re-importing the same syllabus is safe: the course is reused and existing items are skipped.
Each import costs a few cents of API usage.

## Test

```bash
pytest
```

## Layout

```
app.py              entry point and navigation (st.navigation)
pages/              dashboard, import, tbd, rank, experimental, settings
core/               pure logic, no Streamlit imports (enforced by a test)
  timeutil.py       UTC storage, America/Regina display
  extraction.py     extraction schema (pydantic) and review-table logic
  elo.py, priority.py, tiers.py   (Phases 3-4)
services/
  config.py         .env loading
  db.py             SQLite schema and queries
  syllabus_parser.py  Claude extraction (PDF/image blocks, DOCX text, retry once)
  difficulty_rater.py (Phase 5)
tests/              pytest suite
```

## Design decisions beyond SPEC.md

- All-day items (date but no time) are due at 23:59 America/Regina.
- Timestamps are stored as UTC strings like `2026-01-16T05:59:00Z`.
- `items.priority_override` is `high`, `medium`, `low` or NULL.
- `assignment_files` also stores `ai_problem_count` and `ai_topics` (JSON list).
- `rating_matches` freezes `difficulty_used` and `difficulty_overridden` at match time so
  later edits never rewrite history.
- The database enforces SPEC 5.10 where it can: one match per item per mode, completed or
  forfeited items must have a due date, `rating_after = rating_before + delta`, and items
  with rating history cannot be deleted.
- Course colors are assigned automatically from a fixed palette.
- Uploaded assignment files will be stored in `data/uploads/<item_id>/`.
- Group weights are split evenly across items ("Labs 20%, 10 labs" = 2% each), noted in notes.
- A TBD item that had a time in the syllabus keeps it in its notes.
- Extraction uses structured JSON output plus pydantic validation, with server-side refusal
  fallback enabled for models that support it.
