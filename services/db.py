"""SQLite access (SPEC section 6). All timestamps are stored as UTC ISO strings."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.extraction import ITEM_TYPES, NewItem
from core.timeutil import now_utc, to_utc_iso

SCHEMA_VERSION = 1

ITEM_STATUSES = ("pending", "completed", "forfeited", "excused")
PRIORITY_OVERRIDES = ("high", "medium", "low")
RATING_MODES = ("standard", "experimental")

# Assigned to courses in creation order, cycling when exhausted.
COURSE_PALETTE = (
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
    "#B279A2", "#EECA3B", "#9D755D", "#FF9DA6", "#BAB0AC",
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL,
    name        TEXT,
    section     TEXT,
    instructor  TEXT,
    term        TEXT,
    color       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY,
    course_id         INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    type              TEXT NOT NULL CHECK (type IN {_in(ITEM_TYPES)}),
    weight_percent    REAL CHECK (weight_percent IS NULL OR weight_percent BETWEEN 0 AND 100),
    due_at            TEXT,                         -- UTC ISO; NULL = TBD
    all_day           INTEGER NOT NULL DEFAULT 0 CHECK (all_day IN (0, 1)),
    location          TEXT,
    notes             TEXT,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN {_in(ITEM_STATUSES)}),
    completed_at      TEXT,                         -- UTC ISO
    priority_override TEXT CHECK (priority_override IS NULL OR priority_override IN {_in(PRIORITY_OVERRIDES)}),
    confidence        REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    source_quote      TEXT,
    created_at        TEXT NOT NULL,
    -- TBD items cannot be completed or forfeited (SPEC 5.10)
    CHECK (status NOT IN ('completed', 'forfeited') OR due_at IS NOT NULL),
    CHECK (status != 'completed' OR completed_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_items_course ON items(course_id);
CREATE INDEX IF NOT EXISTS idx_items_due ON items(due_at);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);

CREATE TABLE IF NOT EXISTS assignment_files (
    id                       INTEGER PRIMARY KEY,
    item_id                  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    file_path                TEXT NOT NULL,
    ai_difficulty            INTEGER CHECK (ai_difficulty IS NULL OR ai_difficulty BETWEEN 1 AND 10),
    ai_hours                 REAL,
    ai_problem_count         INTEGER,
    ai_topics                TEXT,                  -- JSON list of strings
    ai_justification         TEXT,
    user_override_difficulty INTEGER CHECK (user_override_difficulty IS NULL OR user_override_difficulty BETWEEN 1 AND 10),
    uploaded_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_item ON assignment_files(item_id);

CREATE TABLE IF NOT EXISTS rating_matches (
    id                    INTEGER PRIMARY KEY,
    -- RESTRICT: an item with rating history cannot be deleted, so replay stays valid
    item_id               INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    mode                  TEXT NOT NULL CHECK (mode IN {_in(RATING_MODES)}),
    rating_before         INTEGER NOT NULL,
    opponent_rating       REAL NOT NULL,
    expected              REAL NOT NULL CHECK (expected BETWEEN 0 AND 1),
    score                 REAL NOT NULL CHECK (score IN (0, 0.5, 1)),
    multiplier            REAL NOT NULL CHECK (multiplier BETWEEN 1 AND 1.5),
    k                     INTEGER NOT NULL,
    delta                 INTEGER NOT NULL,
    rating_after          INTEGER NOT NULL,
    difficulty_used       INTEGER CHECK (difficulty_used IS NULL OR difficulty_used BETWEEN 1 AND 10),
    difficulty_overridden INTEGER NOT NULL DEFAULT 0 CHECK (difficulty_overridden IN (0, 1)),
    due_at_snapshot       TEXT NOT NULL,            -- frozen copy of items.due_at
    completed_at          TEXT,                     -- NULL for auto-forfeits
    created_at            TEXT NOT NULL,
    UNIQUE (item_id, mode),                         -- one match per item per mode
    CHECK (rating_after = rating_before + delta)
);
CREATE INDEX IF NOT EXISTS idx_matches_mode ON rating_matches(mode, id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign keys on and dict-like rows. Creates the parent folder."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if missing. Safe to call on every app start."""
    with conn:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextmanager
def open_db(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Connection for one unit of work; commits on success, rolls back on error."""
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# --- settings ---------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --- courses and items ------------------------------------------------------

def next_course_color(conn: sqlite3.Connection) -> str:
    (count,) = conn.execute("SELECT COUNT(*) FROM courses").fetchone()
    return COURSE_PALETTE[count % len(COURSE_PALETTE)]


def add_course(
    conn: sqlite3.Connection,
    code: str,
    name: str | None = None,
    section: str | None = None,
    instructor: str | None = None,
    term: str | None = None,
    color: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO courses (code, name, section, instructor, term, color) VALUES (?, ?, ?, ?, ?, ?)",
        (code, name, section, instructor, term, color or next_course_color(conn)),
    )
    return cur.lastrowid


def add_item(
    conn: sqlite3.Connection,
    course_id: int,
    title: str,
    type: str,
    *,
    weight_percent: float | None = None,
    due_at: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    notes: str | None = None,
    confidence: float | None = None,
    source_quote: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO items (course_id, title, type, weight_percent, due_at, all_day, location,
                              notes, confidence, source_quote, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (course_id, title, type, weight_percent, due_at, int(all_day), location, notes,
         confidence, source_quote, to_utc_iso(now_utc())),
    )
    return cur.lastrowid


def find_course(conn: sqlite3.Connection, code: str, term: str | None) -> int | None:
    """Match an existing course by code (ignoring case and spaces) and term."""
    key = code.replace(" ", "").lower()
    rows = conn.execute("SELECT id, code, term FROM courses").fetchall()
    for row in rows:
        same_term = (row["term"] or "").strip().lower() == (term or "").strip().lower()
        if row["code"].replace(" ", "").lower() == key and same_term:
            return row["id"]
    return None


def save_import(
    conn: sqlite3.Connection,
    course: dict,
    items: list[NewItem],
) -> tuple[int, int, int]:
    """Save a reviewed course and its items. Returns (course_id, added, skipped).

    Re-importing the same syllabus reuses the course and skips items that already exist
    (same title and due date), so nothing is duplicated.
    """
    code = course["code"].strip()
    course_id = find_course(conn, code, course.get("term"))
    if course_id is None:
        course_id = add_course(
            conn, code, name=course.get("name"), section=course.get("section"),
            instructor=course.get("instructor"), term=course.get("term"),
        )
    added = skipped = 0
    for item in items:
        exists = conn.execute(
            "SELECT 1 FROM items WHERE course_id = ? AND lower(title) = lower(?) AND due_at IS ?",
            (course_id, item.title, item.due_at),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        add_item(
            conn, course_id, item.title, item.type, weight_percent=item.weight_percent,
            due_at=item.due_at, all_day=item.all_day, location=item.location, notes=item.notes,
            confidence=item.confidence, source_quote=item.source_quote,
        )
        added += 1
    return course_id, added, skipped


def count_tbd_items(conn: sqlite3.Connection) -> int:
    """Pending items with no due date (shown in the sidebar)."""
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM items WHERE due_at IS NULL AND status = 'pending'"
    ).fetchone()
    return count


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("courses", "items", "assignment_files", "rating_matches")
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
