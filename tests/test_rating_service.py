import json
from datetime import datetime, timedelta, timezone

import pytest

from core.timeutil import to_utc_iso
from services import db, rating
from services.rating import RatingError

NOW = datetime(2026, 2, 13, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "app.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def course(conn):
    return db.add_course(conn, "ME 214")


def _item(conn, course, title="A1", type="assignment", weight=5.0, due=NOW, tbd=False):
    return db.add_item(conn, course, title, type, weight_percent=weight,
                       due_at=None if tbd else to_utc_iso(due))


def _rate_file(conn, item, ai=6, override=None):
    conn.execute("INSERT INTO assignment_files (item_id, file_path, ai_difficulty, user_override_difficulty,"
                 " uploaded_at) VALUES (?, 'f.pdf', ?, ?, ?)", (item, ai, override, to_utc_iso(NOW)))


def test_start_rating(conn):
    assert rating.current_rating(conn, "standard") == (1000, 0)


def test_complete_on_time(conn, course):
    item = _item(conn, course)
    res = rating.complete_item(conn, item, NOW, NOW)
    assert (res.standard.delta, res.standard.rating_after, res.streak) == (23, 1023, 1)
    assert res.experimental is None  # no rated file
    assert rating.current_rating(conn, "standard") == (1023, 1)
    row = conn.execute("SELECT status, completed_at FROM items WHERE id=?", (item,)).fetchone()
    assert row["status"] == "completed" and row["completed_at"] == to_utc_iso(NOW)


def test_complete_late_and_backdated(conn, course):
    item = _item(conn, course, due=NOW - timedelta(hours=20))
    res = rating.complete_item(conn, item, NOW - timedelta(hours=8), NOW)  # 12 h late
    assert res.standard.score == 0.5 and res.standard.delta == 3 and res.streak == 0


def test_tbd_item_cannot_be_completed(conn, course):
    item = _item(conn, course, tbd=True)
    with pytest.raises(RatingError, match="TBD"):
        rating.complete_item(conn, item, NOW, NOW)


def test_cannot_complete_twice_or_in_future(conn, course):
    item = _item(conn, course)
    with pytest.raises(RatingError, match="future"):
        rating.complete_item(conn, item, NOW + timedelta(minutes=1), NOW)
    rating.complete_item(conn, item, NOW, NOW)
    with pytest.raises(RatingError, match="already completed"):
        rating.complete_item(conn, item, NOW, NOW)


def test_experimental_match_when_file_rated(conn, course):
    item = _item(conn, course)
    _rate_file(conn, item, ai=6, override=8)
    res = rating.complete_item(conn, item, NOW, NOW)
    assert res.experimental is not None
    m = conn.execute("SELECT * FROM rating_matches WHERE mode='experimental'").fetchone()
    # Opponent = 700 + 80(8) + 10(5) = 1390 using the override
    assert m["opponent_rating"] == 1390 and m["difficulty_used"] == 8 and m["difficulty_overridden"] == 1
    assert rating.current_rating(conn, "standard")[0] == 1023  # standard unaffected


def test_auto_forfeit(conn, course):
    old = _item(conn, course, "Old", due=NOW - timedelta(hours=49))
    recent = _item(conn, course, "Recent", due=NOW - timedelta(hours=47))
    _item(conn, course, "TBD", tbd=True)
    results = rating.forfeit_overdue(conn, NOW)
    assert [r.title for r in results] == ["Old"]
    assert results[0].standard.delta == -17
    statuses = dict(conn.execute("SELECT id, status FROM items").fetchall())
    assert statuses[old] == "forfeited" and statuses[recent] == "pending"
    assert rating.forfeit_overdue(conn, NOW) == []  # idempotent


def test_placement_then_normal_k(conn, course):
    ks = []
    for i in range(12):
        item = _item(conn, course, f"Q{i}", "quiz", 2)
        ks.append(rating.complete_item(conn, item, NOW, NOW).standard)
    ks = [conn.execute("SELECT k FROM rating_matches WHERE id=?", (o.match_id,)).fetchone()[0] for o in ks]
    assert ks == [40] * 10 + [32] * 2


def test_streak_resets_on_forfeit(conn, course):
    for i in range(3):
        rating.complete_item(conn, _item(conn, course, f"A{i}"), NOW, NOW)
    assert rating.streak(conn) == 3
    _item(conn, course, "Missed", due=NOW - timedelta(days=3))
    rating.forfeit_overdue(conn, NOW)
    assert rating.streak(conn) == 0


def test_undo_within_ten_minutes(conn, course):
    item = _item(conn, course)
    _rate_file(conn, item)
    rating.complete_item(conn, item, NOW, NOW)
    assert rating.undoable_completion(conn, NOW + timedelta(minutes=9))["item_id"] == item
    rating.undo_completion(conn, item, NOW + timedelta(minutes=9))
    assert rating.current_rating(conn, "standard") == (1000, 0)
    assert rating.current_rating(conn, "experimental") == (1000, 0)
    row = conn.execute("SELECT status, completed_at FROM items WHERE id=?", (item,)).fetchone()
    assert (row["status"], row["completed_at"]) == ("pending", None)


def test_undo_expires_and_only_latest(conn, course):
    a, b = _item(conn, course, "A"), _item(conn, course, "B")
    rating.complete_item(conn, a, NOW, NOW)
    rating.complete_item(conn, b, NOW, NOW)
    with pytest.raises(RatingError):
        rating.undo_completion(conn, a, NOW)            # not the latest
    with pytest.raises(RatingError):
        rating.undo_completion(conn, b, NOW + timedelta(minutes=11))  # too late
    assert rating.undoable_completion(conn, NOW + timedelta(minutes=11)) is None


def test_forfeits_are_not_undoable(conn, course):
    _item(conn, course, due=NOW - timedelta(days=3))
    rating.forfeit_overdue(conn, NOW)
    assert rating.undoable_completion(conn, NOW) is None


def test_excused_records_no_match(conn, course):
    item = _item(conn, course, due=NOW - timedelta(days=5))
    rating.set_excused(conn, item, True)
    assert rating.forfeit_overdue(conn, NOW) == []
    assert db.table_counts(conn)["rating_matches"] == 0
    with pytest.raises(RatingError):
        rating.complete_item(conn, item, NOW, NOW)
    rating.set_excused(conn, item, False)
    assert conn.execute("SELECT status FROM items WHERE id=?", (item,)).fetchone()[0] == "pending"


def test_due_snapshot_frozen(conn, course):
    item = _item(conn, course)
    rating.complete_item(conn, item, NOW, NOW)
    db.update_item(conn, item, due_at="2027-01-01T00:00:00Z")
    assert rating.history(conn, "standard")[0]["due_at_snapshot"] == to_utc_iso(NOW)


def test_stored_history_replays_to_current_rating(conn, course):
    for i in range(15):
        due = NOW - timedelta(hours=[0, 30, 60, 12][i % 4]) + timedelta(days=i % 3)
        item = _item(conn, course, f"I{i}", ["quiz", "midterm", "lab"][i % 3], [None, 25, 3][i % 3], due=due)
        if NOW - due > timedelta(hours=48):
            continue
        rating.complete_item(conn, item, min(NOW, due + timedelta(hours=[0, 12, 30][i % 3])), NOW)
    rating.forfeit_overdue(conn, NOW)
    assert rating.check_history(conn, "standard") == []
    from core.elo import StoredMatch, replay
    stored = [StoredMatch(r["rating_before"], r["opponent_rating"], r["score"], r["multiplier"],
                          r["k"], r["delta"], r["rating_after"]) for r in rating.history(conn, "standard")]
    assert replay(stored) == rating.current_rating(conn, "standard")[0]


def test_reset_and_export(conn, course):
    rating.complete_item(conn, _item(conn, course), NOW, NOW)
    data = json.loads(rating.export_all(conn))
    assert len(data["rating_matches"]) == 1 and data["courses"][0]["code"] == "ME 214"
    assert rating.reset_ratings(conn, ("standard",)) == 1
    assert rating.current_rating(conn, "standard") == (1000, 0)
    with pytest.raises(ValueError):
        rating.reset_ratings(conn, ("bogus",))
