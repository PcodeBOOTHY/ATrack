"""AI difficulty rating for the experimental rank (SPEC section 4.6)."""

import re
from dataclasses import dataclass
from pathlib import Path

import anthropic

from core.assessment import TYPE_LABELS
from core.difficulty import DifficultyError, DifficultyRating, parse_rating
from core.timeutil import now_utc
from services import config
from services.claude_client import StructuredCaller, UnsupportedFileError, UploadedDoc, file_blocks

OUTPUT_SCHEMA = anthropic.transform_schema(DifficultyRating)

SYSTEM_PROMPT = """\
You rate how difficult a university assignment or exam is for a typical 2nd-year
engineering student, for a student's study tracker.

Read the attached assignment, lab, project or exam outline and judge it on:
- length: pages, parts, deliverables
- number of problems or questions (count sub-parts as part of their problem)
- concept depth: recall and plug-in vs. derivation, design, open-ended analysis
- multi-step reasoning: how many dependent steps a typical solution needs
- estimated time for a typical 2nd-year engineering student working alone

Scale (be consistent across items; use the whole range):
1-2  a few minutes to an hour of routine practice
3-4  a standard weekly assignment or short quiz
5-6  a substantial problem set or lab report needing several focused hours
7-8  long, multi-concept work: demanding problem sets, big lab reports, midterms
9-10 the hardest work of a term: comprehensive finals, major design projects

Rules:
- estimated_hours: realistic total working time (for an exam: study plus writing time).
- problem_count: null if the document doesn't have countable problems.
- topics: 2 to 8 short phrases naming the main concepts.
- justification: 2 to 3 sentences citing concrete features of the document.
- Base the rating on the document. If it says little (e.g. only a title), rate from the
  item type and weight and say so in the justification.
"""

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ItemContext:
    title: str
    type: str
    course_code: str
    weight_percent: float | None


def build_content(files: list[UploadedDoc], item: ItemContext) -> list[dict]:
    if not files:
        raise UnsupportedFileError("Upload the assignment or exam outline file first.")
    blocks, texts = file_blocks(files)
    weight = f"{item.weight_percent:g}% of the final grade" if item.weight_percent is not None else "weight not stated"
    texts.append(
        f"Item: {item.title} ({TYPE_LABELS.get(item.type, item.type)}) in {item.course_code}, {weight}.\n"
        "Rate its difficulty."
    )
    blocks.append({"type": "text", "text": "\n\n".join(texts)})
    return blocks


class DifficultyRater(StructuredCaller):
    def rate(self, files: list[UploadedDoc], item: ItemContext) -> DifficultyRating:
        return self.call(
            system=SYSTEM_PROMPT,
            content=build_content(files, item),
            schema=OUTPUT_SCHEMA,
            parse=parse_rating,
            error=DifficultyError,
            max_tokens=16000,
        )


def save_uploads(item_id: int, files: list[UploadedDoc], root: Path | None = None) -> str:
    """Store uploaded files under data/uploads/<item_id>/; returns the stored path(s), ';'-joined."""
    folder = (root or config.UPLOADS_DIR) / str(item_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    paths = []
    for f in files:
        target = folder / f"{stamp}_{_SAFE_NAME.sub('_', f.name)}"
        target.write_bytes(f.data)
        paths.append(str(target.relative_to(config.PROJECT_ROOT) if target.is_relative_to(config.PROJECT_ROOT)
                         else target))
    return ";".join(paths)
