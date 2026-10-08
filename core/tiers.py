"""Rank tiers from Wood to Certified Academic Weapon (SPEC section 5.9)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    name: str
    min_rating: int | None   # None = no lower bound
    badge: str
    color: str


TIERS = (
    Tier("Wood", None, "🪵", "#8B5A2B"),
    Tier("Bronze", 1000, "🥉", "#CD7F32"),
    Tier("Silver", 1200, "🥈", "#A8A9AD"),
    Tier("Gold", 1400, "🥇", "#D4AF37"),
    Tier("Platinum", 1600, "💠", "#4FB6C9"),
    Tier("Diamond", 1800, "💎", "#4C7DFF"),
    Tier("Certified Academic Weapon", 2000, "⚔️", "#C0392B"),
)


def tier_index(rating: float) -> int:
    index = 0
    for i, tier in enumerate(TIERS):
        if tier.min_rating is None or rating >= tier.min_rating:
            index = i
    return index


def tier_for(rating: float) -> Tier:
    return TIERS[tier_index(rating)]


def next_tier(rating: float) -> Tier | None:
    i = tier_index(rating)
    return TIERS[i + 1] if i + 1 < len(TIERS) else None


def progress_to_next(rating: float) -> tuple[float, int | None]:
    """(fraction of the way through the current tier, points needed for the next one).

    Wood has no floor, so its bar runs from 800 to 1000. The top tier is always full.
    """
    current, upcoming = tier_for(rating), next_tier(rating)
    if upcoming is None:
        return 1.0, None
    floor = current.min_rating if current.min_rating is not None else upcoming.min_rating - 200
    span = upcoming.min_rating - floor
    fraction = min(max((rating - floor) / span, 0.0), 1.0)
    return fraction, int(upcoming.min_rating - rating)


def tier_change(before: float, after: float) -> int:
    """+1 promoted, -1 demoted, 0 same tier (counts tiers moved, so can be +/-2)."""
    return tier_index(after) - tier_index(before)
