"""Syllabus extraction schema and review-table logic (SPEC section 4.1).

Claude's JSON is validated against these pydantic models. The review step turns the
validated items into editable rows, and turns edited rows back into items ready to save.
"""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.timeutil import local_due_to_utc

ITEM_TYPES = (
    "assignment", "lab", "quiz", "midterm", "final_exam", "project", "presentation", "other",
)
AssessmentType = Literal[
    "assignment", "lab", "quiz", "midterm", "final_exam", "project", "presentation", "other",
]

# Items below this confidence are flagged in the review table.
LOW_CONFIDENCE = 0.7
LOW_CONFIDENCE_FLAG = "⚠️"

# Placeholder text that means "no date yet" (routes the item to TBD).
_NO_DATE_WORDS = ("tba", "tbd", "see canvas", "to be announced", "to be determined", "n/a", "none")


class ExtractionError(Exception):
    """Claude's output could not be turned into a valid extraction."""


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or any(word in stripped.lower() for word in _NO_DATE_WORDS):
            return None
        return stripped
    return value


class ExtractedAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, description="Assessment name as written in the syllabus")
    type: AssessmentType
    weight_percent: float | None = Field(
        ge=0, le=100, description="Percent of final grade for this single item, or null if not stated"
    )
    due_date: date | None = Field(description="ISO date YYYY-MM-DD, or null if TBA/TBD/unknown")
    due_time: str | None = Field(
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="24-hour HH:MM, or null if no time given"
    )
    location: str | None
    notes: str | None
    confidence: float = Field(ge=0, le=1, description="0 to 1: how sure you are this item is correct")
    source_quote: str = Field(description="Short verbatim snippet from the syllabus supporting this item")

    @field_validator("due_date", "due_time", mode="before")
    @classmethod
    def _placeholder_dates_are_null(cls, value: Any) -> Any:
        return _blank_to_none(value)


class CourseInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, description="Course code, e.g. ME 214")
    name: str | None
    section: str | None
    instructor: str | None
    term: str | None = Field(description="e.g. Winter 2026")


class CourseExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course: CourseInfo
    assessments: list[ExtractedAssessment]


class SyllabusExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courses: list[CourseExtraction]


def parse_extraction(text: str) -> SyllabusExtraction:
    """Validate Claude's raw JSON text. Raises ExtractionError with a readable reason."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Output was not valid JSON: {exc}") from exc
    try:
        return SyllabusExtraction.model_validate(data)
    except ValidationError as exc:
        raise ExtractionError(f"Output did not match the schema: {exc}") from exc


# --- review table -----------------------------------------------------------

REVIEW_COLUMNS = (
    "include", "flag", "title", "type", "weight_percent", "due_date", "due_time",
    "location", "notes", "confidence", "source_quote",
)


def is_low_confidence(confidence: float | None) -> bool:
    return confidence is not None and confidence < LOW_CONFIDENCE


def to_review_rows(course: CourseExtraction) -> list[dict[str, Any]]:
    """One editable row per assessment. due_time becomes a datetime.time for the editor."""
    rows = []
    for a in course.assessments:
        rows.append({
            "include": True,
            "flag": LOW_CONFIDENCE_FLAG if is_low_confidence(a.confidence) else "",
            "title": a.title,
            "type": a.type,
            "weight_percent": a.weight_percent,
            "due_date": a.due_date,
            "due_time": time.fromisoformat(a.due_time) if a.due_time else None,
            "location": a.location,
            "notes": a.notes,
            "confidence": a.confidence,
            "source_quote": a.source_quote,
        })
    return rows


@dataclass(frozen=True)
class NewItem:
    """A reviewed item ready to be written to the items table."""

    title: str
    type: str
    weight_percent: float | None
    due_at: str | None  # UTC ISO, None = TBD
    all_day: bool
    location: str | None
    notes: str | None
    confidence: float | None
    source_quote: str | None


def _is_missing(value: Any) -> bool:
    # NaN and pandas NaT both compare unequal to themselves
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        if value != value:
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


def _text(value: Any) -> str | None:
    return None if _is_missing(value) else str(value).strip()


def _to_date(value: Any) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):  # includes pandas Timestamp
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _to_time(value: Any) -> time | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    return time.fromisoformat(str(value).strip()).replace(second=0, microsecond=0)


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    return float(str(value).strip().rstrip("%")) if isinstance(value, str) else float(value)


def rows_to_new_items(rows: list[dict[str, Any]]) -> tuple[list[NewItem], list[str]]:
    """Convert edited review rows into NewItems.

    Rows with include unchecked, or completely empty rows, are skipped.
    Returns (items, errors); errors name the 1-based row number. Save only when errors is empty.
    """
    items: list[NewItem] = []
    errors: list[str] = []
    for n, row in enumerate(rows, start=1):
        include = row.get("include")
        if not _is_missing(include) and not bool(include):
            continue  # unchecked; a new editor row (None) counts as included
        title = _text(row.get("title"))
        if title is None:
            if all(_is_missing(row.get(k)) for k in ("type", "due_date", "weight_percent")):
                continue  # blank row added in the editor
            errors.append(f"Row {n}: title is required.")
            continue

        item_type = _text(row.get("type")) or "other"
        if item_type not in ITEM_TYPES:
            errors.append(f"Row {n} ({title}): unknown type '{item_type}'.")
            continue

        try:
            weight = _to_float(row.get("weight_percent"))
        except ValueError:
            errors.append(f"Row {n} ({title}): weight must be a number.")
            continue
        if weight is not None and not 0 <= weight <= 100:
            errors.append(f"Row {n} ({title}): weight must be between 0 and 100.")
            continue

        try:
            due_date = _to_date(row.get("due_date"))
            due_time = _to_time(row.get("due_time"))
        except ValueError:
            errors.append(f"Row {n} ({title}): date must be YYYY-MM-DD and time HH:MM.")
            continue

        due_at, all_day = (None, False)
        if due_date is not None:
            due_at, all_day = local_due_to_utc(due_date, due_time)

        notes = _text(row.get("notes"))
        if due_date is None and due_time is not None:
            # Keep the time so it isn't lost while the item waits in TBD
            hint = f"Time from syllabus: {due_time.strftime('%H:%M')}"
            notes = f"{notes} | {hint}" if notes else hint

        confidence = row.get("confidence")
        items.append(NewItem(
            title=title,
            type=item_type,
            weight_percent=weight,
            due_at=due_at,
            all_day=all_day,
            location=_text(row.get("location")),
            notes=notes,
            confidence=None if _is_missing(confidence) else float(confidence),
            source_quote=_text(row.get("source_quote")),
        ))
    return items, errors


def total_weight(rows: list[dict[str, Any]]) -> float:
    """Sum of weights of included rows (for the 'adds up to 100%?' hint)."""
    total = 0.0
    for row in rows:
        if row.get("include") is False:
            continue
        try:
            w = _to_float(row.get("weight_percent"))
        except ValueError:
            continue
        total += w or 0.0
    return total
