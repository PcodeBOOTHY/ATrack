"""Streaks and encouraging messages for the reward screen (SPEC section 4.4)."""

from typing import Iterable

ON_TIME_MESSAGES = (
    "Locked in. That's how weapons are forged.",
    "Another one down. The syllabus fears you.",
    "Early bird energy. Future you says thanks.",
    "Clean submission. Keep the streak alive.",
    "That's the discipline that passes finals.",
    "One step closer to Certified Academic Weapon.",
    "Consistency beats cramming. You're proving it.",
    "Professor would be proud. Probably.",
)

LATE_MESSAGES = (
    "Done is better than not done. Next one on time.",
    "Late, but it's in. Reset and go again.",
    "Every finished assignment counts. Plan the next one early.",
)

DEMOTION_MESSAGES = (
    "Rough patch. Ratings bounce back fast with a few on-time wins.",
    "A dip, not a defeat. The next submission is a fresh start.",
)


def on_time_streak(scores_newest_last: Iterable[float]) -> int:
    """Consecutive wins (S = 1) at the end of the match history."""
    streak = 0
    for score in scores_newest_last:
        streak = streak + 1 if score == 1 else 0
    return streak


def pick_message(seed: int, score: float, demoted: bool = False) -> str:
    """Rotates through messages; seed is usually the match id, so it's stable on reruns."""
    if demoted:
        pool = DEMOTION_MESSAGES
    elif score == 1:
        pool = ON_TIME_MESSAGES
    else:
        pool = LATE_MESSAGES
    return pool[seed % len(pool)]
