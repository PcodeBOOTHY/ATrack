"""SPEC 5.11 required tests plus edge cases. Hand calculations are in the comments."""

from datetime import datetime, timedelta, timezone

import pytest

from core.elo import (
    HALF, LOSS, WIN, StoredMatch, actual_score, earliness_multiplier, expected_score, is_forfeit,
    k_factor, opponent_experimental, opponent_standard, play_match, replay, round_half_away,
    verify_history,
)

DUE = datetime(2026, 2, 13, 5, 59, tzinfo=timezone.utc)

# Assignment worth 5%:  R_a = B_type + 10w = 1000 + 10(5) = 1050
# vs R_u = 1000:        E = 1 / (1 + 10^((1050 - 1000)/400)) = 1 / (1 + 10^0.125) = 0.428537
A1_OPPONENT = 1050
A1_EXPECTED = 0.428537


def test_opponent_ratings():
    assert opponent_standard("assignment", 5) == A1_OPPONENT
    assert opponent_standard("midterm", None) == 1300 + 10 * 20      # default w = 20
    assert opponent_standard("final_exam", 40) == 1450 + 400
    # Experimental: 700 + 80d + 10w = 700 + 80(6) + 10(5) = 1230
    assert opponent_experimental(6, "assignment", 5) == 1230
    with pytest.raises(ValueError):
        opponent_experimental(0, "quiz", None)


def test_expected_score():
    assert expected_score(A1_OPPONENT, 1000) == pytest.approx(A1_EXPECTED, abs=1e-6)
    assert expected_score(1000, 1000) == 0.5


def test_on_time_win():
    # S = 1, completed exactly at the deadline -> M = 1, K = 40 (first match)
    # delta = round(40 * 1 * (1 - 0.428537)) = round(22.859) = +23
    s = actual_score(DUE, DUE)
    m = earliness_multiplier(DUE, DUE, s)
    r = play_match(1000, 0, A1_OPPONENT, s, m)
    assert (s, m, r.k, r.delta, r.rating_after) == (WIN, 1.0, 40, 23, 1023)


def test_early_win_at_max_multiplier():
    # 10 days early -> min(10, 7) = 7 -> M = 1 + 0.5 * 7/7 = 1.5
    # delta = round(40 * 1.5 * 0.571463) = round(34.288) = +34
    done = DUE - timedelta(days=10)
    s = actual_score(DUE, done)
    m = earliness_multiplier(DUE, done, s)
    r = play_match(1000, 0, A1_OPPONENT, s, m)
    assert (s, m, r.delta) == (WIN, 1.5, 34)


def test_partial_earliness():
    # 3.5 days early -> M = 1 + 0.5 * 3.5/7 = 1.25
    assert earliness_multiplier(DUE, DUE - timedelta(days=3.5), WIN) == pytest.approx(1.25)


def test_twelve_hours_late_is_half():
    # S = 0.5, M = 1 -> delta = round(40 * (0.5 - 0.428537)) = round(2.859) = +3
    done = DUE + timedelta(hours=12)
    s = actual_score(DUE, done)
    m = earliness_multiplier(DUE, done, s)
    r = play_match(1000, 0, A1_OPPONENT, s, m)
    assert (s, m, r.delta) == (HALF, 1.0, 3)


def test_late_boundaries():
    assert actual_score(DUE, DUE + timedelta(hours=24)) == HALF
    assert actual_score(DUE, DUE + timedelta(hours=24, seconds=1)) == LOSS


def test_auto_forfeit():
    # Not completed 48 h after due -> S = 0
    # delta = round(40 * (0 - 0.428537)) = round(-17.141) = -17
    assert not is_forfeit(DUE, DUE + timedelta(hours=48))
    assert is_forfeit(DUE, DUE + timedelta(hours=48, seconds=1))
    r = play_match(1000, 0, A1_OPPONENT, LOSS, earliness_multiplier(DUE, DUE, LOSS))
    assert (r.multiplier, r.delta, r.rating_after) == (1.0, -17, 983)


def test_placement_k_vs_normal_k():
    # Matches 1-10 use K = 40; from the 11th, K = 32
    # normal: delta = round(32 * 0.571463) = round(18.287) = +18
    assert [k_factor(n) for n in (0, 9, 10, 50)] == [40, 40, 32, 32]
    placement = play_match(1000, 9, A1_OPPONENT, WIN)
    normal = play_match(1000, 10, A1_OPPONENT, WIN)
    assert (placement.k, placement.delta) == (40, 23)
    assert (normal.k, normal.delta) == (32, 18)


def test_rounding_half_away_from_zero():
    assert [round_half_away(x) for x in (20.5, -20.5, 2.4999, -0.5, 0.0)] == [21, -21, 2, -1, 0]


def _history(n=25):
    """Simulate n matches with a mix of results and store them like the database does."""
    rating, stored = 1000, []
    for i in range(n):
        opponent = opponent_standard(["quiz", "assignment", "midterm", "lab"][i % 4], None)
        score = [WIN, WIN, HALF, LOSS, WIN][i % 5]
        mult = 1.0 + 0.1 * (i % 3) if score == WIN else 1.0
        r = play_match(rating, i, opponent, score, mult)
        stored.append(StoredMatch(r.rating_before, r.opponent_rating, r.score, r.multiplier,
                                  r.k, r.delta, r.rating_after))
        rating = r.rating_after
    return stored, rating


def test_full_history_replay_matches_stored_rating():
    stored, current = _history()
    assert replay(stored) == current
    assert verify_history(stored) == []


def test_replay_of_empty_history_is_start_rating():
    assert replay([]) == 1000


def test_verify_detects_tampering():
    stored, _ = _history(5)
    bad = stored[2]
    stored[2] = StoredMatch(bad.rating_before, bad.opponent_rating, bad.score, bad.multiplier,
                            bad.k, bad.delta + 5, bad.rating_after + 5)
    problems = verify_history(stored)
    # match 3's delta is wrong, and match 4 no longer starts from match 3's result
    assert [p.split(":")[0] for p in problems] == ["match 3", "match 4"]
