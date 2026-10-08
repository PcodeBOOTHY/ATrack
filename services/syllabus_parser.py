"""Syllabus extraction with Claude (SPEC section 4.1).

PDFs and images go to Claude as document/image blocks (no OCR). DOCX is converted to
text with python-docx. Output is constrained to a JSON schema, then validated with the
pydantic models in core.extraction; one retry is made if validation fails.
"""

import base64
import io
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath

import anthropic
from docx import Document
from docx.table import Table

from core.extraction import ExtractionError, SyllabusExtraction, parse_extraction
from services import config

MAX_IMAGE_BYTES = 5 * 1024 * 1024    # API limit per image
MAX_PDF_BYTES = 30 * 1024 * 1024     # stay under the 32 MB request limit
MAX_TOKENS = 64000

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", *IMAGE_TYPES)

# Models that accept server-side refusal fallbacks ("default" routing)
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

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


class UnsupportedFileError(ValueError):
    """The uploaded file type or size can't be sent to Claude."""


@dataclass(frozen=True)
class UploadedDoc:
    name: str
    data: bytes


def docx_to_text(data: bytes) -> str:
    """Paragraphs and table rows from a .docx, in document order."""
    doc = Document(io.BytesIO(data))
    lines: list[str] = []
    for block in doc.iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                cells: list[str] = []
                for cell in row.cells:
                    text = cell.text.strip()
                    if not cells or text != cells[-1]:  # merged cells repeat their text
                        cells.append(text)
                if any(cells):
                    lines.append(" | ".join(cells))
        elif block.text.strip():
            lines.append(block.text)
    return "\n".join(lines)


def build_content(files: list[UploadedDoc], pasted_text: str | None, today: date) -> list[dict]:
    """Message content blocks: documents and images first, then text."""
    blocks: list[dict] = []
    texts: list[str] = []
    for f in files:
        ext = PurePath(f.name).suffix.lower()
        if ext == ".pdf":
            if len(f.data) > MAX_PDF_BYTES:
                raise UnsupportedFileError(f"{f.name} is larger than 30 MB.")
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf",
                           "data": base64.standard_b64encode(f.data).decode("ascii")},
                "title": f.name,
            })
        elif ext in IMAGE_TYPES:
            if len(f.data) > MAX_IMAGE_BYTES:
                raise UnsupportedFileError(f"{f.name} is larger than 5 MB. Try a smaller screenshot.")
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": IMAGE_TYPES[ext],
                           "data": base64.standard_b64encode(f.data).decode("ascii")},
            })
        elif ext == ".docx":
            try:
                text = docx_to_text(f.data)
            except Exception as exc:  # python-docx raises several types for bad files
                raise UnsupportedFileError(f"Could not read {f.name} as a Word document.") from exc
            texts.append(f"=== {f.name} ===\n{text}")
        elif ext == ".txt":
            texts.append(f"=== {f.name} ===\n{f.data.decode('utf-8', errors='replace')}")
        else:
            raise UnsupportedFileError(
                f"{f.name}: unsupported file type. Use PDF, DOCX, PNG, JPG or TXT."
            )

    if pasted_text and pasted_text.strip():
        texts.append(f"=== Pasted text ===\n{pasted_text.strip()}")
    if not blocks and not texts:
        raise UnsupportedFileError("Upload at least one file or paste some syllabus text.")

    texts.append(f"Today's date is {today.isoformat()}. Extract every graded assessment.")
    blocks.append({"type": "text", "text": "\n\n".join(texts)})
    return blocks


class SyllabusParser:
    def __init__(self, client=None, model: str | None = None):
        self._client = client
        self.model = model or config.anthropic_model()

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def extract(
        self, files: list[UploadedDoc], pasted_text: str | None = None, today: date | None = None
    ) -> SyllabusExtraction:
        content = build_content(files, pasted_text, today or date.today())
        try:
            text = self._request(content)
            try:
                return parse_extraction(text)
            except ExtractionError as first_error:
                # Retry once, telling Claude what was wrong (SPEC 4.1)
                retry_note = {
                    "type": "text",
                    "text": f"A previous attempt produced invalid output: {first_error}\n"
                            "Return the complete, corrected JSON.",
                }
                return parse_extraction(self._request([*content, retry_note]))
        except anthropic.AuthenticationError as exc:
            raise ExtractionError("Your ANTHROPIC_API_KEY was rejected. Check the key in .env.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ExtractionError("Your API key doesn't have access to this model.") from exc
        except anthropic.NotFoundError as exc:
            raise ExtractionError(f"Model '{self.model}' was not found. Check ANTHROPIC_MODEL in .env.") from exc
        except anthropic.RateLimitError as exc:
            raise ExtractionError("Rate limited by the API. Wait a minute and try again.") from exc
        except anthropic.APIStatusError as exc:
            raise ExtractionError(f"API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError("Could not reach the Anthropic API. Check your internet connection.") from exc

    def _request(self, content: list[dict]) -> str:
        kwargs = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}],
            "output_config": {
                "effort": "medium",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        }
        if self.model in FALLBACK_MODELS:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        with self.client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise ExtractionError("Claude declined to process this file. Try pasting the text instead.")
        if message.stop_reason == "max_tokens":
            raise ExtractionError("The syllabus produced too much output. Try importing one course at a time.")
        return "".join(block.text for block in message.content if block.type == "text")
