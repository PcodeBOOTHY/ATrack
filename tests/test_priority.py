from datetime import datetime, timedelta, timezone

import pytest

from core.priority import (
    difficulty_component, effective_label, label_for, priority_score, urgency_component,
    weight_component,
)

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)


def test_weight_component_caps_at_one():
    assert weight_component("assignment", 10) == 0.25
    assert weight_component("final_exam", 40) == 1.0
    assert weight_component("final_exam", 50) == 1.0


def test_null_weight_uses_type_default():
    # midterm default w = 20 -> 20 / 40
    assert weight_component("midterm", None) == 0.5
    assert weight_component("quiz", None) == 2 / 40


def test_urgency():
    assert urgency_component(NOW - timedelta(hours=1), NOW) == 1.0
    assert urgency_component(NOW, NOW) == 1.0
    assert urgency_component(NOW + timedelta(days=3), NOW) == pytest.approx(0.5)
    assert urgency_component(NOW + timedelta(days=6), NOW) == pytest.approx(1 / 3)
    assert urgency_component(NOW + timedelta(hours=36), NOW) == pytest.approx(1 / 1.5)


def test_difficulty_type_defaults_span_zero_to_one():
    assert difficulty_component("quiz") == 0.0
    assert difficulty_component("final_exam") == 1.0
    assert difficulty_component("assignment") == pytest.approx(100 / 550)


def test_experimental_difficulty_overrides_type_default():
    assert difficulty_component("quiz", 10) == 1.0
    assert difficulty_component("final_exam", 1) == 0.0
    with pytest.raises(ValueError):
        difficulty_component("quiz", 11)


def test_full_score_worked_example():
    # Midterm, 25%, due in 3 days:
    # W = 25/40 = 0.625, U = 1/(1+1) = 0.5, D = (1300-900)/550 = 0.7273
    # P = 0.5*0.625 + 0.35*0.5 + 0.15*0.7273 = 0.3125 + 0.175 + 0.1091 = 0.5966
    p = priority_score("midterm", 25, NOW + timedelta(days=3), NOW)
    assert p == pytest.approx(0.5966, abs=1e-4)
    assert label_for(p) == "medium"


def test_overdue_final_is_max_priority():
    assert priority_score("final_exam", 40, NOW - timedelta(days=1), NOW) == pytest.approx(1.0)


@pytest.mark.parametrize("score,label", [
    (0.6, "high"), (0.5999, "medium"), (0.35, "medium"), (0.3499, "low"), (0.0, "low"),
])
def test_label_boundaries(score, label):
    assert label_for(score) == label


def test_override_wins():
    assert effective_label(0.9, "low") == "low"
    assert effective_label(0.1, None) == "low"
    with pytest.raises(ValueError):
        effective_label(0.5, "urgent")
