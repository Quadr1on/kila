"""Split page text into ~450-token chunks that never cross a page (so every chunk cites one page).

Boundaries prefer headings, then blank lines, then line breaks, then sentence ends. Character
offsets are kept so a citation can point at the exact span on the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 4  # rough for English/technical text; good enough for sizing chunks

_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+\S.{0,80}|[A-Z][A-Z0-9 /&\-]{3,60})$")


@dataclass
class Chunk:
    page: int
    index: int  # position within the page
    char_start: int
    char_end: int
    text: str
    heading: str | None = None


def _split_points(text: str) -> list[int]:
    """Candidate cut positions (character offsets), strongest boundaries first in priority."""
    pts = set()
    for m in re.finditer(r"\n", text):
        line_start = m.end()
        nxt = text.find("\n", line_start)
        line = text[line_start: nxt if nxt != -1 else len(text)].strip()
        if _HEADING.match(line):
            pts.add(line_start)
    return sorted(pts)


def chunk_page(text: str, page: int, target_tokens: int = 450, overlap_tokens: int = 60,
               min_chunk_chars: int = 80) -> list[Chunk]:
    text = text.strip("\n")
    if not text.strip():
        return []
    target = target_tokens * CHARS_PER_TOKEN
    overlap = overlap_tokens * CHARS_PER_TOKEN
    headings = set(_split_points("\n" + text))
    chunks: list[Chunk] = []
    start = 0
    n = len(text)
    heading_starts = {h - 1 for h in headings}  # headings were found in a newline-prefixed copy of text
    while start < n:
        end = min(start + target, n)
        if end < n:
            end = _best_cut(text, start, end, headings)
        piece = text[start:end]
        if piece.strip():
            chunks.append(Chunk(page=page, index=len(chunks), char_start=start, char_end=end, text=piece.strip(),
                                heading=_heading_before(text, start)))
        if end >= n:
            break
        if end in heading_starts:
            start = end  # a new section starts cleanly at its heading: no overlap into the previous one
            continue
        nxt = max(end - overlap, start + 1)
        # don't start the next chunk mid-word
        while nxt < end and not text[nxt - 1].isspace():
            nxt += 1
        start = nxt
    # merge a tiny tail into its predecessor
    if len(chunks) >= 2 and len(chunks[-1].text) < min_chunk_chars:
        tail = chunks.pop()
        prev = chunks[-1]
        prev.char_end = tail.char_end
        prev.text = text[prev.char_start:prev.char_end].strip()
    return chunks


def _best_cut(text: str, start: int, end: int, headings: set[int]) -> int:
    lo = start + int((end - start) * 0.5)  # never cut in the first half of the window
    # heading positions were computed on "\n" + text, i.e. shifted by one
    for h in sorted((h - 1 for h in headings), reverse=True):
        if lo <= h <= end:
            return h
    for pattern in ("\n\n", "\n", ". ", "; ", ", ", " "):
        cut = text.rfind(pattern, lo, end)
        if cut != -1:
            return cut + len(pattern)
    return end


def _heading_before(text: str, pos: int) -> str | None:
    """The heading a chunk sits under: the chunk's own first line if it is one, else the nearest above."""
    first_line_end = text.find("\n", pos)
    upto = text[: first_line_end if first_line_end != -1 else len(text)]
    for line in reversed(upto.splitlines()[-40:]):
        s = line.strip()
        if s and _HEADING.match(s):
            return s[:100]
    return None
