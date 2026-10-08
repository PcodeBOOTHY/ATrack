import json

import pytest

from core.difficulty import DifficultyError, effective_difficulty, parse_rating


def _payload(**overrides):
    data = dict(difficulty=7, estimated_hours=6.5, problem_count=5,
                topics=["rigid body kinematics", " ", "work-energy"],
                justification="Five multi-part problems on rigid bodies. Several need free-body diagrams "
                              "and two-step energy methods.")
    data.update(overrides)
    return json.dumps(data)


def test_valid_rating():
    r = parse_rating(_payload())
    assert r.difficulty == 7 and r.estimated_hours == 6.5
    assert r.topics == ["rigid body kinematics", "work-energy"]  # blanks dropped


def test_problem_count_may_be_null():
    assert parse_rating(_payload(problem_count=None)).problem_count is None


@pytest.mark.parametrize("bad", [
    {"difficulty": 0}, {"difficulty": 11}, {"difficulty": 6.5}, {"estimated_hours": 0},
    {"problem_count": -1}, {"justification": "Hard."}, {"extra": 1},
])
def test_invalid_ratings(bad):
    with pytest.raises(DifficultyError, match="schema"):
        parse_rating(_payload(**bad))


def test_not_json():
    with pytest.raises(DifficultyError, match="JSON"):
        parse_rating("seven")


def test_effective_difficulty():
    assert effective_difficulty(6, None) == (6, False)
    assert effective_difficulty(6, 9) == (9, True)
    assert effective_difficulty(None, None) == (None, False)
