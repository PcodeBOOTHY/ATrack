"""Shared Claude plumbing: file -> content blocks, structured JSON requests, retry, errors.

Used by the syllabus parser (SPEC 4.1) and the difficulty rater (SPEC 4.6).
"""

import base64
import io
from dataclasses import dataclass
from pathlib import PurePath
from typing import Callable, TypeVar

import anthropic
from docx import Document
from docx.table import Table

from services import config

MAX_IMAGE_BYTES = 5 * 1024 * 1024    # API limit per image
MAX_PDF_BYTES = 30 * 1024 * 1024     # stay under the 32 MB request limit

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", *IMAGE_TYPES)

# Models that accept server-side refusal fallbacks ("default" routing)
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

T = TypeVar("T")


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


def file_blocks(files: list[UploadedDoc]) -> tuple[list[dict], list[str]]:
    """(document/image blocks, text sections) for the given files."""
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
            raise UnsupportedFileError(f"{f.name}: unsupported file type. Use PDF, DOCX, PNG, JPG or TXT.")
    return blocks, texts


class StructuredCaller:
    """One Claude request constrained to a JSON schema, validated, retried once if invalid."""

    def __init__(self, client=None, model: str | None = None):
        self._client = client
        self.model = model or config.anthropic_model()

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def call(
        self,
        *,
        system: str,
        content: list[dict],
        schema: dict,
        parse: Callable[[str], T],
        error: type[Exception],
        effort: str = "medium",
        max_tokens: int = 64000,
        too_long_message: str = "The output was too long.",
    ) -> T:
        """parse() must raise `error` for invalid output; that triggers one retry."""
        try:
            text = self._request(system, content, schema, effort, max_tokens, error, too_long_message)
            try:
                return parse(text)
            except error as first_error:
                retry_note = {
                    "type": "text",
                    "text": f"A previous attempt produced invalid output: {first_error}\n"
                            "Return the complete, corrected JSON.",
                }
                return parse(self._request(system, [*content, retry_note], schema, effort, max_tokens,
                                           error, too_long_message))
        except anthropic.AuthenticationError as exc:
            raise error("Your ANTHROPIC_API_KEY was rejected. Check the key in .env.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise error("Your API key doesn't have access to this model.") from exc
        except anthropic.NotFoundError as exc:
            raise error(f"Model '{self.model}' was not found. Check ANTHROPIC_MODEL in .env.") from exc
        except anthropic.RateLimitError as exc:
            raise error("Rate limited by the API. Wait a minute and try again.") from exc
        except anthropic.APIStatusError as exc:
            raise error(f"API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise error("Could not reach the Anthropic API. Check your internet connection.") from exc

    def _request(self, system, content, schema, effort, max_tokens, error, too_long_message) -> str:
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        }
        if self.model in FALLBACK_MODELS:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        with self.client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise error("Claude declined to process this file. Try pasting the text instead.")
        if message.stop_reason == "max_tokens":
            raise error(too_long_message)
        return "".join(block.text for block in message.content if block.type == "text")
