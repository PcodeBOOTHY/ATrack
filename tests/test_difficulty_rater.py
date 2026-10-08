import json
from datetime import datetime, timedelta, timezone

import pytest

from core.difficulty import DifficultyError
from core.timeutil import to_utc_iso
from services import db, rating
from services import difficulty_rater as dr
from services.claude_client import UnsupportedFileError, UploadedDoc
from tests.test_syllabus_parser import FakeClient

ITEM = dr.ItemContext("Assignment 4", "assignment", "ME 214", 5.0)
VALID = json.dumps({"difficulty": 6, "estimated_hours": 5, "problem_count": 4,
                    "topics": ["impulse", "momentum"],
                    "justification": "Four multi-step momentum problems. Two need careful free-body diagrams."})
NOW = datetime(2026, 2, 13, 18, 0, tzinfo=timezone.utc)


def test_content_includes_file_and_item_context():
    blocks = dr.build_content([UploadedDoc("a4.pdf", b"%PDF")], ITEM)
    assert blocks[0]["type"] == "document"
    assert "Assignment 4 (Assignment) in ME 214, 5% of the final grade" in blocks[-1]["text"]


def test_file_required():
    with pytest.raises(UnsupportedFileError):
        dr.build_content([], ITEM)


def test_rate_success_and_request_shape():
    client = FakeClient(VALID)
    result = dr.DifficultyRater(client, model="claude-sonnet-5-5").rate([UploadedDoc("a.txt", b"Q1..")], ITEM)
    assert result.difficulty == 6 and result.topics == ["impulse", "momentum"]
    call = client.calls[0]
    assert call["output_config"]["format"]["schema"]["properties"]["difficulty"]["type"] == "integer"
    assert call["fallbacks"] == "default"


def test_rate_retries_once_then_fails():
    client = FakeClient('{"difficulty": 15}', VALID)
    assert dr.DifficultyRater(client, model="m").rate([UploadedDoc("a.txt", b"x")], ITEM).difficulty == 6
    client = FakeClient("nope", "still nope")
    with pytest.raises(DifficultyError):
        dr.DifficultyRater(client, model="m").rate([UploadedDoc("a.txt", b"x")], ITEM)


def test_refusal_message():
    with pytest.raises(DifficultyError, match="declined"):
        dr.DifficultyRater(FakeClient(("", "refusal")), model="m").rate([UploadedDoc("a.txt", b"x")], ITEM)


def test_save_uploads(tmp_path):
    stored = dr.save_uploads(7, [UploadedDoc("My A4 (final).pdf", b"%PDF"), UploadedDoc("b.png", b"img")],
                             root=tmp_path)
    paths = stored.split(";")
    assert len(paths) == 2 and all("/7/" in p.replace("\\", "/") for p in paths)
    assert "My_A4_final_.pdf" in paths[0]
    assert (tmp_path / "7").exists()


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "app.db")
    db.init_db(c)
    yield c
    c.close()


def _rated_item(conn, ai=6):
    course = db.add_course(conn, "ME 214")
    item = db.add_item(conn, course, "Assignment 4", "assignment", weight_percent=5, due_at=to_utc_iso(NOW))
    file_id = db.add_assignment_file(conn, item, "data/uploads/1/a.pdf", ai_difficulty=ai, ai_hours=5,
                                     ai_problem_count=4, ai_topics=["impulse"], ai_justification="x" * 30)
    return item, file_id


def test_latest_file_and_override(conn):
    item, first = _rated_item(conn, ai=4)
    newer = db.add_assignment_file(conn, item, "b.pdf", ai_difficulty=7, ai_hours=8, ai_problem_count=None,
                                   ai_topics=[], ai_justification="y" * 30)
    rows = db.latest_files(conn)
    assert [r["id"] for r in rows] == [newer] and rows[0]["ai_topics"] == []
    assert rating.item_difficulty(conn, item) == (7, False)
    db.set_difficulty_override(conn, newer, 9)
    assert rating.item_difficulty(conn, item) == (9, True)
    db.set_difficulty_override(conn, newer, None)
    assert rating.item_difficulty(conn, item) == (7, False)


def test_ai_rating_feeds_experimental_match_and_priority(conn):
    item, file_id = _rated_item(conn, ai=6)
    assert db.list_items(conn)[0]["difficulty"] == 6        # priority uses (d - 1) / 9
    db.set_difficulty_override(conn, file_id, 8)
    res = rating.complete_item(conn, item, NOW - timedelta(days=1), NOW)
    # Opponent = 700 + 80(8) + 10(5) = 1390
    m = rating.history(conn, "experimental")[0]
    assert (m["opponent_rating"], m["difficulty_used"], m["difficulty_overridden"]) == (1390, 8, 1)
    assert res.experimental.rating_after != 1000
    assert rating.current_rating(conn, "standard")[0] == res.standard.rating_after  # separate ratings
    # Changing the override afterwards doesn't rewrite history
    db.set_difficulty_override(conn, file_id, 2)
    assert rating.history(conn, "experimental")[0]["difficulty_used"] == 8
    assert db.latest_files(conn)[0]["has_match"] == 1


def test_items_without_files_skip_experimental(conn):
    course = db.add_course(conn, "X")
    item = db.add_item(conn, course, "Quiz", "quiz", due_at=to_utc_iso(NOW))
    res = rating.complete_item(conn, item, NOW, NOW)
    assert res.experimental is None and rating.history(conn, "experimental") == []
