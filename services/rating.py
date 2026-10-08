"""Recording rating matches in the database (SPEC sections 4.4, 5.10).

Each completion or forfeit records one match per mode: always standard, and experimental
too when the item has an AI-rated file. Ratings are never stored separately: the current
rating is the last match's rating_after, so history can always be replayed.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from core.elo import (
    START_RATING, UNDO_WINDOW, StoredMatch, actual_score, earliness_multiplier, is_forfeit,
    opponent_experimental, opponent_standard, play_match, verify_history,
)
from core.rewards import on_time_streak
from core.tiers import Tier, tier_change, tier_for
from core.timeutil import parse_utc_iso, to_utc_iso

MODES = ("standard", "experimental")


class RatingError(Exception):
    """The action isn't allowed (e.g. completing a TBD item)."""


@dataclass(frozen=True)
class MatchOutcome:
    match_id: int
    mode: str
    rating_before: int
    rating_after: int
    delta: int
    score: float
    multiplier: float
    tier_before: Tier
    tier_after: Tier

    @property
    def tier_change(self) -> int:
        return tier_change(self.rating_before, self.rating_after)


@dataclass(frozen=True)
class CompletionResult:
    item_id: int
    title: str
    standard: MatchOutcome
    experimental: MatchOutcome | None
    streak: int


def current_rating(conn: sqlite3.Connection, mode: str) -> tuple[int, int]:
    """(rating, matches played) for a mode."""
    row = conn.execute(
        "SELECT rating_after, (SELECT COUNT(*) FROM rating_matches WHERE mode = ?) AS n "
        "FROM rating_matches WHERE mode = ? ORDER BY id DESC LIMIT 1", (mode, mode),
    ).fetchone()
    return (row["rating_after"], row["n"]) if row else (START_RATING, 0)


def streak(conn: sqlite3.Connection, mode: str = "standard") -> int:
    scores = [r[0] for r in conn.execute(
        "SELECT score FROM rating_matches WHERE mode = ? ORDER BY id", (mode,))]
    return on_time_streak(scores)


def item_difficulty(conn: sqlite3.Connection, item_id: int) -> tuple[int, bool] | None:
    """(difficulty, overridden) from the newest rated file, or None if there isn't one."""
    row = conn.execute(
        "SELECT ai_difficulty, user_override_difficulty FROM assignment_files "
        "WHERE item_id = ? AND (ai_difficulty IS NOT NULL OR user_override_difficulty IS NOT NULL) "
        "ORDER BY id DESC LIMIT 1", (item_id,),
    ).fetchone()
    if row is None:
        return None
    if row["user_override_difficulty"] is not None:
        return row["user_override_difficulty"], True
    return row["ai_difficulty"], False


def _record(
    conn: sqlite3.Connection, item: sqlite3.Row, mode: str, opponent: float, score: float,
    multiplier: float, completed_at: str | None, now: datetime,
    difficulty: tuple[int, bool] | None = None,
) -> MatchOutcome:
    rating, played = current_rating(conn, mode)
    r = play_match(rating, played, opponent, score, multiplier)
    cur = conn.execute(
        """INSERT INTO rating_matches (item_id, mode, rating_before, opponent_rating, expected, score,
               multiplier, k, delta, rating_after, difficulty_used, difficulty_overridden,
               due_at_snapshot, completed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item["id"], mode, r.rating_before, r.opponent_rating, r.expected, r.score, r.multiplier,
         r.k, r.delta, r.rating_after, difficulty[0] if difficulty else None,
         int(difficulty[1]) if difficulty else 0, item["due_at"], completed_at, to_utc_iso(now)),
    )
    return MatchOutcome(cur.lastrowid, mode, r.rating_before, r.rating_after, r.delta, r.score,
                        r.multiplier, tier_for(r.rating_before), tier_for(r.rating_after))


def _play_both_modes(conn, item, score, multiplier, completed_at, now):
    standard = _record(conn, item, "standard", opponent_standard(item["type"], item["weight_percent"]),
                       score, multiplier, completed_at, now)
    experimental = None
    difficulty = item_difficulty(conn, item["id"])
    if difficulty is not None:
        opponent = opponent_experimental(difficulty[0], item["type"], item["weight_percent"])
        experimental = _record(conn, item, "experimental", opponent, score, multiplier,
                               completed_at, now, difficulty)
    return standard, experimental


def _get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row:
    item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise RatingError("Item not found.")
    return item


def complete_item(
    conn: sqlite3.Connection, item_id: int, completed_at: datetime, now: datetime
) -> CompletionResult:
    item = _get_item(conn, item_id)
    if item["due_at"] is None:
        raise RatingError("Give this item a due date before completing it (it's in TBD).")
    if item["status"] != "pending":
        raise RatingError(f"This item is already {item['status']}.")
    if completed_at > now:
        raise RatingError("Completion time can't be in the future.")
    if conn.execute("SELECT 1 FROM rating_matches WHERE item_id = ?", (item_id,)).fetchone():
        raise RatingError("This item already has a rating result.")

    due = parse_utc_iso(item["due_at"])
    score = actual_score(due, completed_at)
    multiplier = earliness_multiplier(due, completed_at, score)
    completed_iso = to_utc_iso(completed_at)
    conn.execute("UPDATE items SET status = 'completed', completed_at = ? WHERE id = ?",
                 (completed_iso, item_id))
    standard, experimental = _play_both_modes(conn, item, score, multiplier, completed_iso, now)
    return CompletionResult(item_id, item["title"], standard, experimental, streak(conn))


@dataclass(frozen=True)
class ForfeitResult:
    title: str
    standard: MatchOutcome
    experimental: MatchOutcome | None


def forfeit_overdue(conn: sqlite3.Connection, now: datetime) -> list[ForfeitResult]:
    """Auto-forfeit pending items more than 48 h past due (run on app start)."""
    results = []
    rows = conn.execute(
        "SELECT * FROM items WHERE status = 'pending' AND due_at IS NOT NULL ORDER BY due_at, id"
    ).fetchall()
    for item in rows:
        if not is_forfeit(parse_utc_iso(item["due_at"]), now):
            continue
        if conn.execute("SELECT 1 FROM rating_matches WHERE item_id = ?", (item["id"],)).fetchone():
            continue
        conn.execute("UPDATE items SET status = 'forfeited' WHERE id = ?", (item["id"],))
        standard, experimental = _play_both_modes(conn, item, 0.0, 1.0, None, now)
        results.append(ForfeitResult(item["title"], standard, experimental))
    return results


def undoable_completion(conn: sqlite3.Connection, now: datetime) -> sqlite3.Row | None:
    """The most recent completion, if it can still be undone (within 10 minutes)."""
    row = conn.execute(
        "SELECT m.*, i.title FROM rating_matches m JOIN items i ON i.id = m.item_id "
        "WHERE m.mode = 'standard' ORDER BY m.id DESC LIMIT 1"
    ).fetchone()
    if row is None or row["completed_at"] is None:
        return None
    if now - parse_utc_iso(row["created_at"]) > UNDO_WINDOW:
        return None
    return row


def undo_completion(conn: sqlite3.Connection, item_id: int, now: datetime) -> None:
    """Fully revert a completion made in the last 10 minutes (only the latest one)."""
    latest = undoable_completion(conn, now)
    if latest is None or latest["item_id"] != item_id:
        raise RatingError("Only your most recent completion can be undone, within 10 minutes.")
    for mode in MODES:
        newest = conn.execute(
            "SELECT item_id FROM rating_matches WHERE mode = ? ORDER BY id DESC LIMIT 1", (mode,)
        ).fetchone()
        has_match = conn.execute(
            "SELECT 1 FROM rating_matches WHERE mode = ? AND item_id = ?", (mode, item_id)).fetchone()
        if has_match and newest["item_id"] != item_id:
            raise RatingError("Another result was recorded after this one, so it can't be undone.")
    conn.execute("DELETE FROM rating_matches WHERE item_id = ?", (item_id,))
    conn.execute("UPDATE items SET status = 'pending', completed_at = NULL WHERE id = ?", (item_id,))


def set_excused(conn: sqlite3.Connection, item_id: int, excused: bool) -> None:
    """Excused items (extension/deferral) record no match."""
    item = _get_item(conn, item_id)
    if excused and item["status"] != "pending":
        raise RatingError(f"Only pending items can be excused (this one is {item['status']}).")
    if not excused and item["status"] != "excused":
        raise RatingError("This item isn't excused.")
    conn.execute("UPDATE items SET status = ? WHERE id = ?", ("excused" if excused else "pending", item_id))


def history(conn: sqlite3.Connection, mode: str) -> list[dict]:
    rows = conn.execute(
        """SELECT m.*, i.title, i.type, c.code AS course_code
             FROM rating_matches m
             JOIN items i ON i.id = m.item_id JOIN courses c ON c.id = i.course_id
            WHERE m.mode = ? ORDER BY m.id""", (mode,),
    ).fetchall()
    return [dict(r) for r in rows]


def check_history(conn: sqlite3.Connection, mode: str) -> list[str]:
    """Replay the mode's history; returns problems (empty = stored rating is consistent)."""
    stored = [StoredMatch(r["rating_before"], r["opponent_rating"], r["score"], r["multiplier"],
                          r["k"], r["delta"], r["rating_after"]) for r in history(conn, mode)]
    return verify_history(stored)


def reset_ratings(conn: sqlite3.Connection, modes: tuple[str, ...]) -> int:
    """Delete match history for the given modes. Completed items stay completed."""
    for mode in modes:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode}")
    placeholders = ", ".join("?" * len(modes))
    return conn.execute(f"DELETE FROM rating_matches WHERE mode IN ({placeholders})", modes).rowcount


def export_all(conn: sqlite3.Connection) -> str:
    """Every table as JSON (Settings → Export)."""
    data = {}
    for table in ("courses", "items", "assignment_files", "rating_matches", "settings"):
        data[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    return json.dumps(data, indent=2)
