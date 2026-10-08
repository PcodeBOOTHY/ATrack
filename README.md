# Academic Weapon

A local, single-user assignment tracker. Upload course syllabi, let Claude extract every
assessment, review it, and track your work with an Elo rank from Wood to Certified Academic
Weapon. See [SPEC.md](SPEC.md) for the full design.

**Status:** Phase 1 (project structure, SQLite schema, navigation shell).

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
| `ANTHROPIC_API_KEY` | From Phase 2 | (none) | Claude API key for syllabus import and difficulty rating |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-5-5` | Model used for extraction |
| `APP_DB_PATH` | No | `data/app.db` | SQLite file (relative paths resolve from the project root) |

## Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501. The database is created automatically at `data/app.db`
on first start. `data/` and `.env` are git-ignored.

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
  elo.py, priority.py, tiers.py   (Phases 3-4)
services/
  config.py         .env loading
  db.py             SQLite schema and queries
  syllabus_parser.py, difficulty_rater.py   (Phases 2, 5)
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
