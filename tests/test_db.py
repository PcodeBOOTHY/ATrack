import sqlite3

import pytest

from services import db

PAST = "2026-01-16T05:59:00Z"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "nested" / "app.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def course_id(conn):
    return db.add_course(conn, "ME 214", name="Dynamics")


def _match(conn, item_id, mode="standard", **overrides):
    row = dict(item_id=item_id, mode=mode, rating_before=1000, opponent_rating=1030.0,
               expected=0.457, score=1, multiplier=1.0, k=40, delta=22, rating_after=1022,
               due_at_snapshot=PAST, completed_at=PAST, created_at=PAST)
    row.update(overrides)
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO rating_matches ({cols}) VALUES ({', '.join('?' * len(row))})",
                 tuple(row.values()))


def test_creates_db_file_and_parent_dir(tmp_path):
    path = tmp_path / "a" / "b" / "app.db"
    db.init_db(db.connect(path))
    assert path.exists()


def test_all_tables_exist(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"courses", "items", "assignment_files", "rating_matches", "settings"} <= names


def test_init_is_idempotent_and_keeps_data(conn, course_id):
    db.init_db(conn)
    assert db.table_counts(conn)["courses"] == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_item(conn, 999, "Ghost", "quiz")


def test_invalid_type_rejected(conn, course_id):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_item(conn, course_id, "Bad", "homework")


@pytest.mark.parametrize("field,value", [("weight_percent", 150), ("confidence", 1.5)])
def test_out_of_range_values_rejected(conn, course_id, field, value):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_item(conn, course_id, "Bad", "quiz", **{field: value})


def test_tbd_item_cannot_be_completed(conn, course_id):
    item = db.add_item(conn, course_id, "Lab 3", "lab")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE items SET status='completed', completed_at=? WHERE id=?", (PAST, item))


def test_dated_item_can_be_completed(conn, course_id):
    item = db.add_item(conn, course_id, "Lab 3", "lab", due_at=PAST)
    conn.execute("UPDATE items SET status='completed', completed_at=? WHERE id=?", (PAST, item))


def test_priority_override_values(conn, course_id):
    item = db.add_item(conn, course_id, "Quiz 1", "quiz")
    conn.execute("UPDATE items SET priority_override='high' WHERE id=?", (item,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE items SET priority_override='urgent' WHERE id=?", (item,))


def test_tbd_count_only_counts_pending_undated(conn, course_id):
    db.add_item(conn, course_id, "Dated", "quiz", due_at=PAST)
    db.add_item(conn, course_id, "TBD 1", "quiz")
    excused = db.add_item(conn, course_id, "TBD excused", "quiz")
    conn.execute("UPDATE items SET status='excused' WHERE id=?", (excused,))
    assert db.count_tbd_items(conn) == 1


def test_one_match_per_item_per_mode(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment", due_at=PAST)
    _match(conn, item, "standard")
    _match(conn, item, "experimental")
    with pytest.raises(sqlite3.IntegrityError):
        _match(conn, item, "standard")


def test_match_rating_arithmetic_enforced(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment", due_at=PAST)
    with pytest.raises(sqlite3.IntegrityError):
        _match(conn, item, rating_after=1050)


def test_match_requires_due_snapshot(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment", due_at=PAST)
    with pytest.raises(sqlite3.IntegrityError):
        _match(conn, item, due_at_snapshot=None)


def test_item_with_history_cannot_be_deleted(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment", due_at=PAST)
    _match(conn, item)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM items WHERE id=?", (item,))


def test_difficulty_range_on_files(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO assignment_files (item_id, file_path, ai_difficulty, uploaded_at)"
                     " VALUES (?, 'x.pdf', 11, ?)", (item, PAST))


def test_settings_round_trip(conn):
    assert db.get_setting(conn, "theme", "light") == "light"
    db.set_setting(conn, "theme", "dark")
    db.set_setting(conn, "theme", "dark2")
    assert db.get_setting(conn, "theme") == "dark2"


def test_course_colors_cycle(conn):
    ids = [db.add_course(conn, f"C{i}") for i in range(len(db.COURSE_PALETTE) + 1)]
    colors = [conn.execute("SELECT color FROM courses WHERE id=?", (i,)).fetchone()[0] for i in ids]
    assert colors[0] == db.COURSE_PALETTE[0]
    assert colors[-1] == db.COURSE_PALETTE[0]
    assert len(set(colors[:-1])) == len(db.COURSE_PALETTE)


def test_open_db_rolls_back_on_error(tmp_path):
    path = tmp_path / "app.db"
    with db.open_db(path) as c:
        db.init_db(c)
    with pytest.raises(RuntimeError):
        with db.open_db(path) as c:
            db.add_course(c, "ME 214")
            raise RuntimeError
    with db.open_db(path) as c:
        assert db.table_counts(c)["courses"] == 0


# --- save_import ------------------------------------------------------------

from core.extraction import NewItem  # noqa: E402


def _new(title="A1", due_at=PAST, **kw):
    base = dict(title=title, type="assignment", weight_percent=5.0, due_at=due_at, all_day=False,
                location=None, notes=None, confidence=0.9, source_quote="A1 5%")
    base.update(kw)
    return NewItem(**base)


COURSE = {"code": "ME 214", "name": "Dynamics", "section": "01", "instructor": "Dr. S", "term": "Winter 2026"}


def test_save_import_creates_course_and_items(conn):
    course_id, added, skipped = db.save_import(conn, COURSE, [_new("A1"), _new("Quiz", due_at=None)])
    assert (added, skipped) == (2, 0)
    assert db.count_tbd_items(conn) == 1
    row = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    assert row["instructor"] == "Dr. S" and row["color"] == db.COURSE_PALETTE[0]


def test_reimport_reuses_course_and_skips_duplicates(conn):
    first, _, _ = db.save_import(conn, COURSE, [_new("A1"), _new("Quiz", due_at=None)])
    again = dict(COURSE, code="me214")  # same course, different spacing/case
    second, added, skipped = db.save_import(conn, again, [_new("a1"), _new("Quiz", due_at=None), _new("A2")])
    assert first == second
    assert (added, skipped) == (1, 2)
    assert db.table_counts(conn)["courses"] == 1


def test_same_code_different_term_is_new_course(conn):
    a, _, _ = db.save_import(conn, COURSE, [_new()])
    b, _, _ = db.save_import(conn, dict(COURSE, term="Fall 2026"), [_new()])
    assert a != b


def test_save_import_is_atomic(tmp_path):
    path = tmp_path / "app.db"
    with db.open_db(path) as c:
        db.init_db(c)
    with pytest.raises(sqlite3.IntegrityError):
        with db.open_db(path) as c:
            db.save_import(c, COURSE, [_new("ok"), _new("bad", weight_percent=500)])
    with db.open_db(path) as c:
        assert db.table_counts(c) == {"courses": 0, "items": 0, "assignment_files": 0, "rating_matches": 0}


# --- Phase 3 queries --------------------------------------------------------

def test_list_items_joins_course_and_difficulty(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment", due_at=PAST)
    conn.execute("INSERT INTO assignment_files (item_id, file_path, ai_difficulty, user_override_difficulty,"
                 " uploaded_at) VALUES (?, 'a.pdf', 4, 7, ?)", (item, PAST))
    db.add_item(conn, course_id, "TBD", "quiz")
    rows = db.list_items(conn)
    assert [r["title"] for r in rows] == ["A1", "TBD"]  # dated first
    assert rows[0]["course_code"] == "ME 214" and rows[0]["difficulty"] == 7
    assert rows[1]["difficulty"] is None


def test_set_due_moves_item_out_of_tbd(conn, course_id):
    item = db.add_item(conn, course_id, "Project", "project")
    assert [r["id"] for r in db.list_tbd_items(conn)] == [item]
    db.set_item_due(conn, item, PAST, all_day=True)
    assert db.list_tbd_items(conn) == [] and db.count_tbd_items(conn) == 0
    row = conn.execute("SELECT due_at, all_day FROM items WHERE id=?", (item,)).fetchone()
    assert (row["due_at"], row["all_day"]) == (PAST, 1)


def test_update_item_rejects_unknown_fields(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment")
    db.update_item(conn, item, priority_override="high", notes="bring calculator")
    assert conn.execute("SELECT priority_override FROM items WHERE id=?", (item,)).fetchone()[0] == "high"
    with pytest.raises(ValueError):
        db.update_item(conn, item, status="completed")


def test_due_edit_does_not_change_match_snapshot(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment", due_at=PAST)
    _match(conn, item)
    db.update_item(conn, item, due_at="2026-03-01T05:59:00Z")
    snap = conn.execute("SELECT due_at_snapshot FROM rating_matches WHERE item_id=?", (item,)).fetchone()[0]
    assert snap == PAST


def test_delete_item(conn, course_id):
    item = db.add_item(conn, course_id, "A1", "assignment")
    db.delete_item(conn, item)
    assert db.table_counts(conn)["items"] == 0
