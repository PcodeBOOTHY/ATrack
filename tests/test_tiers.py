import pytest

from core.rewards import DEMOTION_MESSAGES, LATE_MESSAGES, ON_TIME_MESSAGES, on_time_streak, pick_message
from core.tiers import TIERS, next_tier, progress_to_next, tier_change, tier_for


@pytest.mark.parametrize("rating,name", [
    (999, "Wood"), (1000, "Bronze"), (1199, "Bronze"), (1200, "Silver"), (1399, "Silver"),
    (1400, "Gold"), (1600, "Platinum"), (1999, "Diamond"), (2000, "Certified Academic Weapon"),
    (2500, "Certified Academic Weapon"), (400, "Wood"),
])
def test_tier_boundaries(rating, name):
    assert tier_for(rating).name == name


def test_tiers_are_ordered():
    floors = [t.min_rating for t in TIERS[1:]]
    assert floors == sorted(floors)


def test_progress_to_next():
    # Bronze 1000-1199: 1100 is halfway, 100 points to Silver
    assert progress_to_next(1100) == (0.5, 100)
    assert progress_to_next(1000) == (0.0, 200)
    assert progress_to_next(900) == (0.5, 100)       # Wood bar runs 800-1000
    assert progress_to_next(500) == (0.0, 500)
    assert progress_to_next(2100) == (1.0, None)
    assert next_tier(1999).name == "Certified Academic Weapon"


def test_tier_change():
    assert tier_change(999, 1000) == 1
    assert tier_change(1000, 999) == -1
    assert tier_change(1010, 1150) == 0
    assert tier_change(1190, 1410) == 2


def test_streak_counts_trailing_wins():
    assert on_time_streak([]) == 0
    assert on_time_streak([1, 1, 0.5, 1, 1, 1]) == 3
    assert on_time_streak([1, 1, 0]) == 0


def test_messages_rotate_by_seed():
    assert pick_message(0, 1) == ON_TIME_MESSAGES[0]
    assert pick_message(len(ON_TIME_MESSAGES) + 1, 1) == ON_TIME_MESSAGES[1]
    assert pick_message(3, 0.5) in LATE_MESSAGES
    assert pick_message(3, 1, demoted=True) in DEMOTION_MESSAGES
