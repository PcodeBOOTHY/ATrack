"""Elo rating engine (SPEC section 5).

    Opponent (standard):      R_a = B_type + 10 * w
    Opponent (experimental):  R_a = 700 + 80 * d + 10 * w
    Expected score:           E = 1 / (1 + 10 ** ((R_a - R_u) / 400))
    Earliness (wins only):    M = 1 + 0.5 * min(days_early, 7) / 7
    Update:                   delta = round(K * M * (S - E)),  R_u' = R_u + delta

round() rounds halves away from zero (+20.5 -> +21, -20.5 -> -21).
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from core.assessment import BASE_RATING, effective_weight

START_RATING = 1000
PLACEMENT_MATCHES = 10
K_PLACEMENT = 40
K_NORMAL = 32

HALF_CREDIT_WINDOW = timedelta(hours=24)
FORFEIT_AFTER = timedelta(hours=48)
MAX_EARLY_DAYS = 7
UNDO_WINDOW = timedelta(minutes=10)

WIN, HALF, LOSS = 1.0, 0.5, 0.0


def round_half_away(x: float) -> int:
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def opponent_standard(item_type: str, weight_percent: float | None) -> float:
    return BASE_RATING[item_type] + 10 * effective_weight(item_type, weight_percent)


def opponent_experimental(difficulty: int, item_type: str, weight_percent: float | None) -> float:
    if not 1 <= difficulty <= 10:
        raise ValueError("difficulty must be 1 to 10")
    return 700 + 80 * difficulty + 10 * effective_weight(item_type, weight_percent)


def expected_score(opponent: float, rating: float) -> float:
    return 1 / (1 + 10 ** ((opponent - rating) / 400))


def actual_score(due_at: datetime, completed_at: datetime) -> float:
    """1 on time, 0.5 up to 24 h late, 0 beyond that."""
    if completed_at <= due_at:
        return WIN
    if completed_at - due_at <= HALF_CREDIT_WINDOW:
        return HALF
    return LOSS


def is_forfeit(due_at: datetime, now: datetime) -> bool:
    """A pending item more than 48 h past due is forfeited (S = 0)."""
    return now - due_at > FORFEIT_AFTER


def earliness_multiplier(due_at: datetime, completed_at: datetime, score: float) -> float:
    if score != WIN:
        return 1.0
    days_early = max(0.0, (due_at - completed_at).total_seconds() / 3600 / 24)
    return 1 + 0.5 * min(days_early, MAX_EARLY_DAYS) / MAX_EARLY_DAYS


def k_factor(matches_played: int) -> int:
    """K = 40 for the first 10 matches in a mode, then 32."""
    return K_PLACEMENT if matches_played < PLACEMENT_MATCHES else K_NORMAL


@dataclass(frozen=True)
class MatchResult:
    rating_before: int
    opponent_rating: float
    expected: float
    score: float
    multiplier: float
    k: int
    delta: int
    rating_after: int


def play_match(
    rating: int, matches_played: int, opponent: float, score: float, multiplier: float = 1.0
) -> MatchResult:
    e = expected_score(opponent, rating)
    k = k_factor(matches_played)
    delta = round_half_away(k * multiplier * (score - e))
    return MatchResult(rating, opponent, e, score, multiplier, k, delta, rating + delta)


@dataclass(frozen=True)
class StoredMatch:
    """The parts of a rating_matches row needed to replay and check it."""

    rating_before: int
    opponent_rating: float
    score: float
    multiplier: float
    k: int
    delta: int
    rating_after: int


def replay(matches: Iterable[StoredMatch]) -> int:
    """Recompute the current rating from match history, in order."""
    rating = START_RATING
    for n, m in enumerate(matches):
        rating = play_match(rating, n, m.opponent_rating, m.score, m.multiplier).rating_after
    return rating


def verify_history(matches: list[StoredMatch]) -> list[str]:
    """Problems found when replaying stored history (empty list = consistent)."""
    problems = []
    rating = START_RATING
    for n, m in enumerate(matches):
        r = play_match(rating, n, m.opponent_rating, m.score, m.multiplier)
        if (m.rating_before, m.k, m.delta, m.rating_after) != (r.rating_before, r.k, r.delta, r.rating_after):
            problems.append(
                f"match {n + 1}: stored {m.rating_before}{m.delta:+d}={m.rating_after} (K={m.k}), "
                f"replay {r.rating_before}{r.delta:+d}={r.rating_after} (K={r.k})"
            )
        rating = m.rating_after  # keep checking each match against its own stored start
    return problems
