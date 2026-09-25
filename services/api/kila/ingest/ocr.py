"""OCR engine: PP-OCR detection + recognition models run by RapidOCR on onnxruntime.

Model paths are always passed explicitly, so RapidOCR never reaches its own download code.
A missing model is a clear error telling the admin to run scripts/predownload.py.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

from kila.ingest.envelope import OcrLine
from kila.settings import REPO_ROOT

log = logging.getLogger(__name__)


class OcrUnavailable(RuntimeError):
    pass


def _bundled_dir() -> Path:
    import rapidocr

    return Path(os.path.dirname(rapidocr.__file__)) / "models"


class OcrEngine:
    def __init__(self, rec_model: str, min_score: float = 0.5):
        from rapidocr import RapidOCR

        bundled = _bundled_dir()
        rec = bundled / "PP-OCRv6_rec_small.onnx" if rec_model == "bundled" else _resolve(rec_model)
        paths = {
            "Det.model_path": bundled / "PP-OCRv6_det_small.onnx",
            "Cls.model_path": bundled / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "Rec.model_path": rec,
        }
        for key, p in paths.items():
            if not Path(p).exists():
                raise OcrUnavailable(f"OCR model missing: {p}. Run scripts/predownload.py --only hf --yes while online.")
        params = {k: str(v) for k, v in paths.items()}
        params.update({"Global.log_level": "error", "Global.text_score": min_score})
        self._engine = RapidOCR(params=params)
        self._lock = threading.Lock()  # onnxruntime sessions are shared; keep one page at a time

    def read(self, img_rgb: np.ndarray) -> list[OcrLine]:
        with self._lock:
            out = self._engine(img_rgb)
        if out.txts is None:
            return []
        return [OcrLine(text=t, conf=round(float(s), 4), box=np.asarray(b).round(1).tolist())
                for t, s, b in zip(out.txts, out.scores, out.boxes)]


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


_engines: dict[str, OcrEngine] = {}
_engines_lock = threading.Lock()


def get_engine(lang: str, languages: dict, min_score: float) -> OcrEngine:
    spec = languages.get(lang)
    if spec is None or spec.get("rec_model") is None:
        raise OcrUnavailable(f"no OCR recognition model for language '{lang}'")
    with _engines_lock:
        if lang not in _engines:
            _engines[lang] = OcrEngine(spec["rec_model"], min_score)
        return _engines[lang]


# ------------------------------------------------------------------ layout

def lines_to_text(lines: list[OcrLine]) -> str:
    """Rebuild reading order: group detections into rows by vertical overlap, then left-to-right.

    PP-OCR returns table cells as separate detections; joining a row's cells keeps
    'C3 Nozzle N3 (outlet) 11.5 9.8 6.2 0.425 8.5' together, which matters for retrieval.
    """
    if not lines:
        return ""
    items = []
    for ln in lines:
        ys = [p[1] for p in ln.box]
        xs = [p[0] for p in ln.box]
        items.append((min(ys), max(ys), min(xs), ln.text))
    heights = sorted(b - t for t, b, _, _ in items)
    med_h = heights[len(heights) // 2] or 1.0
    items.sort(key=lambda it: (it[0] + it[1]) / 2)
    rows: list[list[tuple]] = []
    for it in items:
        cy = (it[0] + it[1]) / 2
        if rows:
            last = rows[-1]
            last_cy = sum((r[0] + r[1]) / 2 for r in last) / len(last)
            if abs(cy - last_cy) < 0.55 * med_h:
                last.append(it)
                continue
        rows.append([it])
    return "\n".join(" ".join(r[3] for r in sorted(row, key=lambda r: r[2])) for row in rows)


def mean_conf(lines: list[OcrLine]) -> float | None:
    if not lines:
        return None
    # weight by text length so a confident heading doesn't hide a shaky paragraph
    w = np.array([max(len(ln.text), 1) for ln in lines], dtype=float)
    c = np.array([ln.conf for ln in lines])
    return round(float((w * c).sum() / w.sum()), 4)
