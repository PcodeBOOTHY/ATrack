# Academic Weapon

A single-user assignment tracker that runs on your computer, with optional Google sign-in
that saves your data to your own Google Drive. Upload course syllabi, let Claude extract every
assessment, review it, and track your work with an Elo rank from Wood to Certified Academic
Weapon. See [SPEC.md](SPEC.md) for the full design.

**Status:** All 5 phases done: import, TBD + dashboard, Elo rank, experimental rank, Google Drive sync.

## Quick start (Windows): double-click `start.bat`

1. Get the code: on GitHub click **Code → Download ZIP** and unzip it (or `git pull` if you
   already have it).
2. Open the folder and double-click **`start.bat`**. The first time it:
   - installs Python if your computer doesn't have it,
   - sets up the app's packages (a few minutes),
   - asks for your Anthropic API key (get one at https://console.anthropic.com).
3. Your browser opens the app at http://localhost:8501. Keep the black window open while you
   use it; close it to stop the app.

After the first time, double-clicking `start.bat` starts the app in a few seconds.
On macOS or Linux, run `bash start.sh` instead.

## Manual setup

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
| `ALLOWED_EMAIL` | With Google sign-in | (none) | The only Google account allowed to sign in |

## Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501. The database is created automatically at `data/app.db`
on first start. `data/` and `.env` are git-ignored.

## Google sign-in and Drive sync (optional)

Without this the app runs "local only" and your data stays in `data/app.db` on this computer.
With it, you sign in with Google and the database is saved to a hidden app folder in **your**
Google Drive, so it follows you between computers.

One-time setup in the Google Cloud console (free, no billing needed):

1. Go to https://console.cloud.google.com and create a project (e.g. "Academic Weapon").
2. **APIs & Services → Library**: search **Google Drive API** and click **Enable**.
3. **Google Auth Platform** (called "OAuth consent screen" in some versions) → **Get started**:
   app name "Academic Weapon", your email as support/contact email, audience **External**.
4. **Audience → Test users → Add users**: add your own Gmail address.
5. **Data Access → Add or remove scopes**: tick `.../auth/drive.appdata`
   ("See, create, and delete its own configuration data in your Google Drive"), then **Update** and **Save**.
6. **Clients → Create client**: type **Web application**. Under **Authorized redirect URIs**
   add `http://localhost:8501/oauth2callback`. Click **Create** and copy the Client ID and secret.
7. In the project folder, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
   and paste in the client ID and secret. For `cookie_secret`, paste the output of
   `python -c "import secrets; print(secrets.token_hex(32))"`.
8. In `.env`, set `ALLOWED_EMAIL` to your Gmail address.
9. Restart `streamlit run app.py` and click **Sign in with Google**. Google will warn that the
   app isn't verified (it's your own private app): click **Continue** and allow access.

How sync works:

- On sign-in, the app downloads your data from Drive if another computer saved newer data.
- After every change, it uploads the new copy. The sidebar shows the last sync time.
- If two computers changed things without syncing, it asks which copy to keep. The other
  copy is saved in `data/backups/`, so nothing is lost.
- Google's Drive permission lasts about an hour per sign-in. If the sidebar says
  "sign in again", click it; your changes are kept on this computer and upload after you sign in.

## Importing a syllabus

1. Open **Import Syllabus**, upload PDF / DOCX / PNG / JPG / TXT files, or paste text.
2. Click **Extract assessments**. Claude reads the files and returns every graded item.
3. Review the table. ⚠️ marks items with confidence below 70%; compare them with the
   source quote. Edit any cell, untick **Save** to skip a row, or add rows.
4. Click **Confirm and save**. Items without a due date go to TBD.

Re-importing the same syllabus is safe: the course is reused and existing items are skipped.
Each import costs a few cents of API usage.

## Dashboard and TBD

- **TBD** lists items with no date, grouped by course. Pick a date (and optionally a time)
  and click **Save**; the item moves to the dashboard.
- **Dashboard** tabs: By Priority, By Type, By Course, This Week (overdue + next 7 days),
  Completed. Filter by course, type and status.
- Priority score `P = 0.5·W + 0.35·U + 0.15·D` (see SPEC 4.3): High ≥ 0.60, Medium ≥ 0.35.
  Use **Edit an item** to change dates or weights, or to set a manual High/Medium/Low (✋).

## Completing work and your rank

- On the dashboard, select a row (click its left edge) and press **Mark complete**. Choose
  "Just now" or the time you actually finished. A reward screen shows your rating change,
  tier progress and on-time streak. **Undo** is available for 10 minutes (most recent only).
- **Excused** (extension/deferral) removes an item from rating entirely.
- Scoring (SPEC 5): on time = win (bonus up to ×1.5 for finishing up to 7 days early),
  up to 24 h late = half, later = loss. Items still pending 48 h after the deadline are
  forfeited automatically when the app starts.
- **Rank** shows both ratings, the tier ladder, a rating chart and full match history.
- **Settings** has JSON export and rating reset.

## Experimental rank

- On **Experimental Rank → Rate an assignment**, pick a pending item and upload the actual
  assignment / lab / exam outline (PDF, Word, screenshot or text). Claude returns a difficulty
  (1-10), estimated hours, problem count, topics and a short justification.
- When that item is completed, it also plays a match in the experimental rating against
  `700 + 80 x difficulty + 10 x weight`. Items without a rated file are left out of it.
- **Rated items** lets you override the AI difficulty (shown as ✋ in match history). Once an
  item is finished its experimental result is final.
- The difficulty also feeds the dashboard priority score (`D = (d - 1) / 9`).
- Uploaded files are kept in `data/uploads/` on this computer; only the ratings sync to Drive.

## Test

```bash
pytest
```

## Layout

```
start.bat / start.sh  one-click launchers (install, set up, run)
app.py              entry point: sign-in, sync, navigation
views/              dashboard, import, tbd, rank, experimental, settings (pages; not named
                    "pages/" so Streamlit doesn't auto-discover them and bypass app.py)
ui/                 Streamlit helpers (sign-in + sync screens, item tables)
core/               pure logic, no Streamlit imports (enforced by a test)
  timeutil.py       UTC storage, America/Regina display
  extraction.py     extraction schema (pydantic) and review-table logic
  assessment.py     item types and per-type defaults (B_type, default weight)
  priority.py       priority score and labels
  dashboard.py      filtering, sorting, grouping, This Week
  sync.py           upload / download / conflict decision for Drive sync
  elo.py            Elo math: opponents, expected/actual score, K, earliness, replay
  tiers.py          Wood ... Certified Academic Weapon, progress to next tier
  rewards.py        streaks and encouraging messages
  difficulty.py     difficulty rating schema (pydantic)
services/
  config.py         .env loading
  db.py             SQLite schema and queries
  syllabus_parser.py  Claude extraction (PDF/image blocks, DOCX text, retry once)
  drive_sync.py     Google Drive client and sync
  rating.py         completing, forfeiting, undo, excused, history, reset, export
  claude_client.py  shared Claude plumbing: files -> blocks, JSON schema, retry, errors
  difficulty_rater.py AI difficulty rating (SPEC 4.6)
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
- Difficulty `D` in the priority score is the type's base rating scaled to 0..1
  (quiz 0, final exam 1), or `(d - 1) / 9` once an experimental difficulty exists.
- "This Week" means overdue plus the next 7 days (rolling), not the calendar week.
- Accounts: Google sign-in for one allowed address; data lives in that account's Google Drive
  app-data folder (replaces SPEC's "no accounts" for this user's setup).
- Elo `round()` rounds halves away from zero (+20.5 -> +21), not Python's banker's rounding.
- Undo only applies to the most recent completion, so later matches never need recomputing.
- Forfeits count toward the 10 placement matches; the on-time streak resets on any
  half/loss/forfeit and ignores excused items.
- You can back-date a completion (never into the future); scoring uses that time.
- A file uploaded after an item is completed doesn't create a retroactive experimental match,
  and changing an override never rewrites a recorded match.
- Page files live in `views/`, not `pages/`: Streamlit treats a `pages/` folder specially,
  which can show raw file names in the sidebar.
