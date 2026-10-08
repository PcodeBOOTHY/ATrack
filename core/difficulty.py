"""AI difficulty rating schema for the experimental rank (SPEC section 4.6)."""

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class DifficultyError(Exception):
    """Claude's difficulty rating could not be produced or validated."""


class DifficultyRating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    difficulty: int = Field(ge=1, le=10, description="1 (trivial) to 10 (hardest) for a 2nd-year engineering student")
    estimated_hours: float = Field(gt=0, le=200, description="Typical hours for a 2nd-year engineering student")
    problem_count: int | None = Field(ge=0, description="Number of problems/questions, or null if not countable")
    topics: list[str] = Field(description="Main topics covered, short phrases")
    justification: str = Field(min_length=20, description="2 to 3 sentences explaining the rating")

    @field_validator("topics")
    @classmethod
    def _clean_topics(cls, topics: list[str]) -> list[str]:
        cleaned = [t.strip() for t in topics if t and t.strip()]
        return cleaned[:10]


def parse_rating(text: str) -> DifficultyRating:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DifficultyError(f"Output was not valid JSON: {exc}") from exc
    try:
        return DifficultyRating.model_validate(data)
    except ValidationError as exc:
        raise DifficultyError(f"Output did not match the schema: {exc}") from exc


def effective_difficulty(ai: int | None, override: int | None) -> tuple[int | None, bool]:
    """(difficulty used for rating, whether it's the user's override)."""
    if override is not None:
        return override, True
    return ai, False
