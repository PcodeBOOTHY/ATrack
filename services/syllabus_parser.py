"""Syllabus extraction with Claude (SPEC section 4.1).

PDFs and images go to Claude as document/image blocks (no OCR). DOCX is converted to
text with python-docx. Output is constrained to a JSON schema, then validated with the
pydantic models in core.extraction; one retry is made if validation fails.
"""

from datetime import date

import anthropic

from core.extraction import ExtractionError, SyllabusExtraction, parse_extraction
from services.claude_client import (  # noqa: F401  (re-exported for the import page and tests)
    FALLBACK_BETA, MAX_IMAGE_BYTES, SUPPORTED_EXTENSIONS, StructuredCaller, UnsupportedFileError,
    UploadedDoc, docx_to_text, file_blocks,
)

OUTPUT_SCHEMA = anthropic.transform_schema(SyllabusExtraction)

SYSTEM_PROMPT = """\
You extract graded assessments from university course syllabi for a student's assignment tracker.

Return every graded item: assignments, labs, quizzes, midterms, final exams, projects,
presentations, and anything else that counts toward the grade ("other").

Rules:
- One entry in "courses" per distinct course in the input. Usually there is one.
- weight_percent is the weight of ONE item. If a group is weighted together
  ("Labs 20%, 10 labs"), split it evenly (2.0 each) and say so in notes.
  Use null if no weight is stated.
- due_date is ISO YYYY-MM-DD. due_time is 24-hour HH:MM. Use null for anything not
  stated or marked TBA, TBD, "see Canvas/LMS", or similar. Never guess a date.
- Infer the year from the term (e.g. "Winter 2026"). If the year is not stated anywhere,
  assume the academic term nearest to today's date given below.
- Recurring items ("weekly quiz every Friday", "lab reports due each Monday"): if the
  term start/end dates or a week-by-week schedule make the dates clear, expand them
  into individual dated items (Quiz 1, Quiz 2, ...), skipping stated breaks. If the dates
  are ambiguous, create the items with due_date null and explain the pattern in notes.
- final_exam is for the final exam only; use midterm for midterms and term tests.
- location: room or "online", if stated. notes: anything useful the student should know
  (format, allowed aids, submission method), kept short.
- confidence: 0 to 1. Use below 0.7 when you had to interpret, split, or infer something.
- source_quote: a short verbatim snippet (under 200 characters) from the syllabus that
  supports the item.
- If the input contains no syllabus or no graded items, return {"courses": []}.
"""


def build_content(files: list[UploadedDoc], pasted_text: str | None, today: date) -> list[dict]:
    """Message content blocks: documents and images first, then text."""
    blocks, texts = file_blocks(files)
    if pasted_text and pasted_text.strip():
        texts.append(f"=== Pasted text ===\n{pasted_text.strip()}")
    if not blocks and not texts:
        raise UnsupportedFileError("Upload at least one file or paste some syllabus text.")
    texts.append(f"Today's date is {today.isoformat()}. Extract every graded assessment.")
    blocks.append({"type": "text", "text": "\n\n".join(texts)})
    return blocks


class SyllabusParser(StructuredCaller):
    def extract(
        self, files: list[UploadedDoc], pasted_text: str | None = None, today: date | None = None
    ) -> SyllabusExtraction:
        return self.call(
            system=SYSTEM_PROMPT,
            content=build_content(files, pasted_text, today or date.today()),
            schema=OUTPUT_SCHEMA,
            parse=parse_extraction,
            error=ExtractionError,
            too_long_message="The syllabus produced too much output. Try importing one course at a time.",
        )
