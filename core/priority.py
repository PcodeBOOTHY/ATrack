"""Priority score (SPEC section 4.3).

    W = min(w / 40, 1)              w = weight_percent, or the type default when null
    U = 1 if overdue, else 1 / (1 + days_until_due / 3)
    D = difficulty normalized to 0..1
    P = 0.5*W + 0.35*U + 0.15*D

D is the type's base rating scaled over the quiz..final_exam range, or (d - 1) / 9 when an
experimental difficulty d (1 to 10) is available.
"""

from datetime import datetime

from core.assessment import BASE_RATING, effective_weight

W_WEIGHT, W_URGENCY, W_DIFFICULTY = 0.5, 0.35, 0.15
HIGH_THRESHOLD, MEDIUM_THRESHOLD = 0.6, 0.35

LABELS = ("high", "medium", "low")
LABEL_RANK = {"high": 2, "medium": 1, "low": 0}

_MIN_BASE, _MAX_BASE = min(BASE_RATING.values()), max(BASE_RATING.values())


def weight_component(item_type: str, weight_percent: float | None) -> float:
    return min(effective_weight(item_type, weight_percent) / 40, 1.0)


def urgency_component(due_at: datetime, now: datetime) -> float:
    if due_at <= now:
        return 1.0
    days_until_due = (due_at - now).total_seconds() / 86400
    return 1 / (1 + days_until_due / 3)


def difficulty_component(item_type: str, difficulty: int | None = None) -> float:
    if difficulty is not None:
        if not 1 <= difficulty <= 10:
            raise ValueError("difficulty must be 1 to 10")
        return (difficulty - 1) / 9
    return (BASE_RATING[item_type] - _MIN_BASE) / (_MAX_BASE - _MIN_BASE)


def priority_score(
    item_type: str,
    weight_percent: float | None,
    due_at: datetime,
    now: datetime,
    difficulty: int | None = None,
) -> float:
    w = weight_component(item_type, weight_percent)
    u = urgency_component(due_at, now)
    d = difficulty_component(item_type, difficulty)
    return W_WEIGHT * w + W_URGENCY * u + W_DIFFICULTY * d


def label_for(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def effective_label(score: float, override: str | None) -> str:
    """The user's manual override wins over the computed label."""
    if override is not None:
        if override not in LABEL_RANK:
            raise ValueError(f"invalid priority override: {override}")
        return override
    return label_for(score)
