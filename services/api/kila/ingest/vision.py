"""Second opinion from the local vision model for pages OCR can't read confidently.

Used for handwriting, low-confidence scans and scripts PP-OCR has no model for (Kannada).
Both readings are kept; they are never silently merged.
"""

from __future__ import annotations

import base64
import difflib
import io
import re

import numpy as np
from PIL import Image

from kila.ingest.envelope import VisionCheck
from kila.models.registry import get_registry

PROMPT = (
    "Transcribe all text in this image exactly as written, line by line. Keep numbers, units and tag "
    "numbers exactly. If a word is illegible write [illegible]. Output only the transcription."
)


def _png_data_url(img: np.ndarray, max_side: int = 1600) -> str:
    im = Image.fromarray(img)
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def similarity(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()  # noqa: E731
    return round(difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


def transcribe(img: np.ndarray, role: str, ocr_text: str | None, disagreement_below: float,
               language_hint: str | None = None) -> VisionCheck:
    reg = get_registry()
    spec = reg.spec(role)
    prompt = PROMPT + (f" The text is in {language_hint}." if language_hint else "")
    try:
        llm = reg.get_llm(role, temperature=0, max_tokens=1500)
        msg = llm.invoke([{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _png_data_url(img)}},
        ]}])
        text = msg.content if isinstance(msg.content, str) else ""
    except Exception as e:  # model missing / server down: keep the OCR result, record why
        return VisionCheck(model=spec.name, text="", error=f"{type(e).__name__}: {e}"[:300])
    sim = similarity(ocr_text, text) if ocr_text else None
    return VisionCheck(model=spec.name, text=text.strip(), similarity=sim,
                       disagrees=sim is not None and sim < disagreement_below)
