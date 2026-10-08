import json
import math
from datetime import date, datetime, time

import pytest

from core.extraction import (
    LOW_CONFIDENCE_FLAG, ExtractionError, SyllabusExtraction, parse_extraction,
    rows_to_new_items, to_review_rows, total_weight,
)


def _assessment(**overrides):
    a = dict(title="Assignment 1", type="assignment", weight_percent=5.0, due_date="2026-01-23",
             due_time="23:59", location=None, notes=None, confidence=0.95,
             source_quote="Assignment 1 (5%) due Jan 23")
    a.update(overrides)
    return a


def _payload(*assessments):
    return json.dumps({"courses": [{
        "course": {"code": "ME 214", "name": "Dynamics", "section": "01",
                   "instructor": "Dr. Smith", "term": "Winter 2026"},
        "assessments": list(assessments) or [_assessment()],
    }]})


# --- parsing ----------------------------------------------------------------

def test_parses_valid_output():
    result = parse_extraction(_payload())
    a = result.courses[0].assessments[0]
    assert result.courses[0].course.code == "ME 214"
    assert a.due_date == date(2026, 1, 23) and a.due_time == "23:59"


@pytest.mark.parametrize("placeholder", ["TBA", "TBD", "see Canvas", "To be announced", "", "  "])
def test_placeholder_dates_become_null(placeholder):
    a = parse_extraction(_payload(_assessment(due_date=placeholder, due_time=placeholder)))
    item = a.courses[0].assessments[0]
    assert item.due_date is None and item.due_time is None


def test_invalid_json_raises():
    with pytest.raises(ExtractionError, match="not valid JSON"):
        parse_extraction("{not json")


@pytest.mark.parametrize("bad", [
    {"type": "homework"},
    {"confidence": 1.4},
    {"weight_percent": 140},
    {"due_time": "25:00"},
    {"due_date": "Jan 23"},
    {"title": ""},
])
def test_schema_violations_raise(bad):
    with pytest.raises(ExtractionError, match="schema"):
        parse_extraction(_payload(_assessment(**bad)))


def test_extra_fields_rejected():
    with pytest.raises(ExtractionError):
        parse_extraction(_payload(_assessment(extra="x")))


def test_empty_course_list_is_valid():
    assert parse_extraction('{"courses": []}').courses == []


# --- review rows ------------------------------------------------------------

def _course(*assessments):
    return parse_extraction(_payload(*assessments)).courses[0]


def test_low_confidence_flagged():
    rows = to_review_rows(_course(_assessment(confidence=0.69), _assessment(confidence=0.7)))
    assert [r["flag"] for r in rows] == [LOW_CONFIDENCE_FLAG, ""]


def test_review_row_types():
    row = to_review_rows(_course())[0]
    assert row["include"] is True
    assert row["due_date"] == date(2026, 1, 23)
    assert row["due_time"] == time(23, 59)


def test_round_trip_timed_item_to_utc():
    items, errors = rows_to_new_items(to_review_rows(_course(_assessment(due_time="14:30"))))
    assert errors == []
    assert items[0].due_at == "2026-01-23T20:30:00Z" and items[0].all_day is False


def test_date_without_time_is_all_day():
    items, _ = rows_to_new_items(to_review_rows(_course(_assessment(due_time=None))))
    assert items[0].due_at == "2026-01-24T05:59:00Z" and items[0].all_day is True


def test_no_date_routes_to_tbd():
    items, _ = rows_to_new_items(to_review_rows(_course(_assessment(due_date="TBA", due_time=None))))
    assert items[0].due_at is None


def test_tbd_item_keeps_time_in_notes():
    items, _ = rows_to_new_items(to_review_rows(_course(_assessment(due_date=None, due_time="10:00"))))
    assert items[0].due_at is None
    assert "10:00" in items[0].notes


def test_unchecked_rows_skipped():
    rows = to_review_rows(_course(_assessment(title="Keep"), _assessment(title="Drop")))
    rows[1]["include"] = False
    items, _ = rows_to_new_items(rows)
    assert [i.title for i in items] == ["Keep"]


def test_blank_added_row_ignored_but_partial_row_errors():
    blank = {k: None for k in ("include", "title", "type", "due_date", "weight_percent")}
    partial = {"include": True, "title": None, "type": "quiz"}
    items, errors = rows_to_new_items([blank, partial])
    assert items == [] and errors == ["Row 2: title is required."]


def test_editor_values_from_pandas_style_cells():
    # data_editor can hand back NaN, NaT-like values, Timestamps and strings
    row = {"include": True, "title": "Lab 2", "type": "lab", "weight_percent": float("nan"),
           "due_date": datetime(2026, 2, 3, 0, 0), "due_time": "09:30", "location": float("nan"),
           "notes": "", "confidence": 0.8, "source_quote": "Lab 2"}
    items, errors = rows_to_new_items([row])
    assert errors == []
    item = items[0]
    assert item.weight_percent is None and item.location is None and item.notes is None
    assert item.due_at == "2026-02-03T15:30:00Z"


def test_new_row_without_type_defaults_to_other():
    items, _ = rows_to_new_items([{"title": "Bonus", "include": None}])
    assert items[0].type == "other" and items[0].due_at is None


@pytest.mark.parametrize("field,value,message", [
    ("weight_percent", 120, "between 0 and 100"),
    ("weight_percent", "lots", "must be a number"),
    ("type", "homework", "unknown type"),
    ("due_date", "next week", "YYYY-MM-DD"),
])
def test_bad_edits_reported(field, value, message):
    rows = to_review_rows(_course())
    rows[0][field] = value
    items, errors = rows_to_new_items(rows)
    assert items == [] and message in errors[0]


def test_weight_with_percent_sign_accepted():
    rows = to_review_rows(_course())
    rows[0]["weight_percent"] = "12.5%"
    items, _ = rows_to_new_items(rows)
    assert math.isclose(items[0].weight_percent, 12.5)


def test_total_weight_ignores_excluded_and_null():
    rows = to_review_rows(_course(_assessment(weight_percent=30), _assessment(weight_percent=None),
                                  _assessment(weight_percent=20)))
    rows[2]["include"] = False
    assert total_weight(rows) == 30


def test_schema_is_json_serializable():
    json.dumps(SyllabusExtraction.model_json_schema())
