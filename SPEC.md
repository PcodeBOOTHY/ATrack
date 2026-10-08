# SPEC.md: Academic Weapon (Local Assignment Tracker)

## 1. Overview
A single-user, local Python app. The user uploads course syllabi, Claude extracts every
assessment, the user reviews it, and confirmed items are saved to the tracker. Items
with missing dates go to a TBD section. Assessments are sorted by type and priority.
Completing work triggers a reward screen and updates an Elo rating with ranks from Wood
to Certified Academic Weapon. A separate "Experimental Rank" uses AI-estimated
difficulty from uploaded assignment files.

Runs locally with `streamlit run app.py`. No accounts, no login, no hosting.
Timezone: America/Regina (no DST). Store timestamps in UTC, display in local time.

## 2. Tech Stack
- Python 3.11+, Streamlit (UI), SQLite via the standard sqlite3 module (file: data/app.db)
- Anthropic Python SDK. Model from env var ANTHROPIC_MODEL (default: claude-sonnet-5-5).
  Send PDFs and images directly to Claude as document/image content blocks (no OCR).
  DOCX: extract text with python-docx.
- pydantic for validating AI JSON output
- pytest for tests
- python-dotenv for .env
- .gitignore must include: .env, data/

## 3. Project Structure
- app.py: entry point, navigation
- pages/: dashboard, import, tbd, rank, experimental, settings
- core/ (pure logic, no Streamlit imports, fully unit tested):
  - elo.py, priority.py, tiers.py
- services/: db.py, syllabus_parser.py, difficulty_rater.py
- tests/
- requirements.txt, .env.example, README.md (setup + run instructions)

## 4. Features

### 4.1 Syllabus Import
- Upload one or more files (PDF, DOCX, PNG/JPG) or paste raw text.
- Claude returns strict JSON. Validate with pydantic; retry once on invalid output.
- Course fields: code, name, section, instructor, term.
- Assessment fields per item:
  - title
  - type: one of [assignment, lab, quiz, midterm, final_exam, project, presentation, other]
  - weight_percent (float | null)
  - due_date (ISO date | null), due_time (HH:MM | null)
  - location (str | null), notes (str | null)
  - confidence (0 to 1)
  - source_quote (short snippet from the syllabus supporting the extraction)
- Recurring items ("weekly quiz every Friday") are expanded into individual dated items
  when term dates allow; if ambiguous, create them in TBD with a note.
- "TBA", "TBD", "see Canvas", or missing dates mean due_date = null (routes to TBD).
- REVIEW STEP (mandatory): show items in st.data_editor, flag confidence < 0.7, show
  source_quote. Nothing is saved until the user clicks Confirm.

### 4.2 TBD Section
- Lists items with no due date, grouped by course, with inline date/time inputs.
- Once a date is set, the item leaves TBD and appears in the dashboard views.
- Show TBD count in the sidebar.

### 4.3 Dashboard and Sorting
Views (tabs): By Priority (default), By Type, By Course, This Week, Completed.
Filters: course, type, status.

Priority score (0 to 1), in core/priority.py:
  W = min(weight_percent / 40, 1)        (null weight uses type default, see 5.2)
  U = 1 if overdue, else 1 / (1 + days_until_due / 3)
  D = difficulty normalized 0 to 1 (type default, or experimental if available)
  P = 0.5*W + 0.35*U + 0.15*D
Labels: High if P >= 0.6, Medium if 0.35 <= P < 0.6, Low if P < 0.35.
User can set a manual priority override per item.

### 4.4 Completion and Reward Screen
- Marking an item complete opens an st.dialog reward screen with:
  - Celebration animation (st.balloons plus custom confetti via components.html)
  - Elo change (e.g. "+21") and new rating
  - Progress bar toward the next tier
  - On-time streak counter
  - Rotating encouraging message
- Tier promotion shows a larger rank-up screen with the new tier name and badge.
- Tier demotion shows a quieter, non-shaming message.
- Undo completion within 10 minutes fully reverts the rating change.

### 4.5 Rank Page
Current rating and tier for both modes, tier ladder, match history table, and a line
chart of rating over time.

### 4.6 Experimental Rank
- Separate rating and history, same tiers, clearly labeled
  "Experimental: AI-estimated difficulty". Never affects the standard rank.
- User uploads the actual assignment/exam outline file for an item.
- Claude returns JSON: difficulty (integer 1 to 10), estimated_hours, problem_count,
  topics[], justification (2 to 3 sentences). Rubric: length, number of problems,
  concept depth, multi-step reasoning, estimated time for a typical 2nd-year
  engineering student.
- Items without an uploaded file are excluded from experimental rank only.
- User can override AI difficulty; overridden items are flagged in history.

### 4.7 Settings
Export data to JSON, reset ratings (with confirmation).

## 5. Elo System (exact math, core/elo.py, fully tested)

### 5.1 Player
Start at R_u = 1000 in each mode.

### 5.2 Opponent rating, Standard mode
  R_a = B_type + 10 * w
B_type: quiz 900, assignment 1000, lab 1050, presentation 1050, project 1200,
midterm 1300, final_exam 1450, other 1000.
Default w when weight is null: quiz 2, assignment 3, lab 3, presentation 5,
project 10, midterm 20, final_exam 35, other 3.

### 5.3 Opponent rating, Experimental mode
  R_a = 700 + 80 * d + 10 * w      (d = difficulty 1 to 10)

### 5.4 Expected score
  E = 1 / (1 + 10^((R_a - R_u) / 400))

### 5.5 Actual score S
- Completed on or before due: S = 1
- Completed up to 24 h late: S = 0.5
- Completed more than 24 h late: S = 0
- Not completed 48 h after due: auto-forfeit, S = 0 (checked on app start)
- Status "excused" (extension/deferral): no match recorded

### 5.6 Earliness multiplier (wins only)
  d_early = max(0, hours early / 24)
  M = 1 + 0.5 * min(d_early, 7) / 7     (only when S = 1; otherwise M = 1)

### 5.7 K-factor
K = 40 for the first 10 matches in a mode, then K = 32.

### 5.8 Update
  delta = round(K * M * (S - E))
  R_u_new = R_u + delta

### 5.9 Tiers
Wood < 1000 | Bronze 1000 to 1199 | Silver 1200 to 1399 | Gold 1400 to 1599 |
Platinum 1600 to 1799 | Diamond 1800 to 1999 | Certified Academic Weapon >= 2000

### 5.10 Integrity
- TBD items cannot be completed for rating.
- One match per item per mode.
- Store due_at_snapshot in each match; later due date edits do not change history.
- Current rating must be recomputable by replaying the match history in order.

### 5.11 Required tests
On-time win, early win at max multiplier, 12 h late (S = 0.5), auto-forfeit,
placement K vs normal K, tier boundaries (999, 1000, 1999, 2000), full history replay
matching the stored rating.

## 6. Data Model (SQLite)
- courses(id, code, name, section, instructor, term, color)
- items(id, course_id, title, type, weight_percent, due_at (nullable), all_day, location,
  notes, status [pending, completed, forfeited, excused], completed_at,
  priority_override, confidence, source_quote)
- assignment_files(id, item_id, file_path, ai_difficulty, ai_hours, ai_justification,
  user_override_difficulty)
- rating_matches(id, item_id, mode [standard, experimental], rating_before,
  opponent_rating, expected, score, multiplier, k, delta, rating_after,
  due_at_snapshot, completed_at, created_at)
- settings(key, value)

## 7. Build Phases (stop after each for review)
1. Project structure, requirements, SQLite schema, Streamlit navigation shell, README
2. Syllabus upload, Claude extraction, review screen, save to DB
3. TBD page, dashboard views, sorting, filters, priority score (with tests)
4. Elo engine (with tests), completion flow, reward screen, rank page
5. Experimental rank

## 8. Out of Scope for Now
Google Calendar sync (planned for a later phase), mobile app, hosting, multiple users,
grade/GPA tracking, LMS import.