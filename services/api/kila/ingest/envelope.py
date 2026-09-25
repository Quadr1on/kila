"""TaskEnvelope: the single structure every downstream step (router, RAG, agent) reads (spec §6.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

AttachmentKind = Literal["pdf_text", "pdf_scanned", "pdf_mixed", "image", "sheet", "docx", "code", "text", "unsupported"]
PageMethod = Literal["text_layer", "ocr", "ocr+vision", "vision", "none"]


class OcrLine(BaseModel):
    text: str
    conf: float
    box: list[list[float]]  # 4 corner points in page-image pixels (after deskew)


class VisionCheck(BaseModel):
    model: str
    text: str
    similarity: float | None = None  # vs OCR text, 0..1
    disagrees: bool = False
    error: str | None = None


class Page(BaseModel):
    index: int  # 1-based page number
    method: PageMethod
    text: str
    ocr_conf: float | None = None  # mean line confidence, OCR pages only
    image_object_id: str | None = None  # rendered page image (thumbnails bucket)
    image_size: tuple[int, int] | None = None
    skew_deg: float | None = None
    lines: list[OcrLine] = Field(default_factory=list)
    vision: VisionCheck | None = None


class SheetTable(BaseModel):
    name: str
    n_rows: int
    n_cols: int
    columns: list[str]
    dtypes: dict[str, str]
    preview: list[list[str]]  # first rows, stringified
    rows_json: list[dict] = Field(default_factory=list)  # full table (records); capped by limits


class CodeFile(BaseModel):
    path: str
    size: int
    language: str | None = None
    text: str | None = None  # None when skipped (binary or over the cap)


class Attachment(BaseModel):
    object_id: str
    sha256: str
    name: str
    mime: str
    kind: AttachmentKind
    language: str = "en"
    pages: list[Page] = Field(default_factory=list)
    tables: list[SheetTable] = Field(default_factory=list)
    code: list[CodeFile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)


class TaskEnvelope(BaseModel):
    id: str
    user_text: str = ""
    language: str = "en"
    attachments: list[Attachment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def detect_language(text: str) -> str:
    """Script-based: Devanagari -> hi, Kannada -> kn, else en. Good enough to pick OCR/prompt language."""
    counts = {"hi": 0, "kn": 0, "latin": 0}
    for ch in text:
        o = ord(ch)
        if 0x0900 <= o <= 0x097F:
            counts["hi"] += 1
        elif 0x0C80 <= o <= 0x0CFF:
            counts["kn"] += 1
        elif ch.isalpha():
            counts["latin"] += 1
    best = max(counts, key=counts.get)
    return best if best in ("hi", "kn") and counts[best] > 0 else "en"
