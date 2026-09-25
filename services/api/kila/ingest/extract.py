"""Per-type extraction: bytes on disk -> Attachment (pages / tables / code).

Page images and OCR go through callbacks so this module stays free of storage and DB concerns.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from kila.ingest import preprocess
from kila.ingest.envelope import Attachment, CodeFile, Page, SheetTable, detect_language
from kila.ingest.ocr import OcrUnavailable, get_engine, lines_to_text, mean_conf
from kila.ingest.vision import transcribe
from kila.pdfium_guard import PDFIUM_LOCK

CODE_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".cs": "csharp", ".go": "go", ".rs": "rust",
    ".sql": "sql", ".sh": "shell", ".ps1": "powershell", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".toml": "toml", ".md": "markdown", ".ini": "ini", ".m": "matlab", ".r": "r", ".vb": "vb", ".bas": "vb",
}
SHEET_EXT = {".xlsx", ".xlsm", ".csv"}
LANG_NAMES = {"hi": "Hindi", "kn": "Kannada", "en": "English"}

StoreImage = Callable[[np.ndarray, str], tuple[str, tuple[int, int]]]  # (img, name) -> (object_id, (w, h))
Progress = Callable[[int, int], None]


def classify(name: str, mime: str) -> str:
    ext = Path(name).suffix.lower()
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("image/") and mime != "image/svg+xml":
        return "image"
    if ext in SHEET_EXT or mime in ("text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
        return "sheet"
    if ext == ".docx":
        return "docx"
    if ext == ".zip" or mime == "application/zip":
        return "zip"
    if ext in CODE_EXT:
        return "code"
    if mime.startswith("text/"):
        return "text"
    return "unsupported"


class Extractor:
    def __init__(self, cfg: dict[str, Any], store_image: StoreImage, progress: Progress | None = None):
        self.cfg = cfg
        self.store_image = store_image
        self.progress = progress or (lambda done, total: None)
        self.vision_budget = cfg["vision_fallback"]["max_pages"]

    # ------------------------------------------------------------ entry

    def run(self, path: Path, *, object_id: str, sha256: str, name: str, mime: str, lang: str) -> Attachment:
        att = Attachment(object_id=object_id, sha256=sha256, name=name, mime=mime, kind="unsupported", language=lang)
        t0 = time.perf_counter()
        kind = classify(name, mime)
        if kind == "pdf":
            self._pdf(path, att)
        elif kind == "image":
            self._image(path, att)
        elif kind == "sheet":
            self._sheet(path, att)
        elif kind == "docx":
            self._docx(path, att)
        elif kind == "zip":
            self._zip(path, att)
        elif kind in ("code", "text"):
            self._textfile(path, att, kind)
        else:
            att.warnings.append(f"No extractor for {mime}; stored but not readable yet.")
        if att.pages and lang == "auto":
            att.language = detect_language(att.full_text[:5000])
        att.timings_ms["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return att

    # ------------------------------------------------------------ PDF

    def _pdf(self, path: Path, att: Attachment) -> None:
        import pypdfium2 as pdfium

        pcfg, lim = self.cfg["pdf"], self.cfg["limits"]
        # PDFium isn't thread-safe: hold the lock only for PDFium calls, never during OCR.
        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(str(path))
            n = len(pdf)
        try:
            if n > lim["max_pages"]:
                att.warnings.append(f"Only the first {lim['max_pages']} of {n} pages were read.")
            n = min(n, lim["max_pages"])
            methods = set()
            for i in range(n):
                with PDFIUM_LOCK:
                    page = pdf[i]
                    text = _norm(page.get_textpage().get_text_range())
                    scanned = len(text) < pcfg["scanned_min_chars_per_page"]
                    dpi = pcfg["render_dpi"] if scanned else 100
                    img = np.asarray(page.render(scale=dpi / 72).to_pil().convert("RGB"))
                    page.close()
                if not scanned:
                    oid, size = self.store_image(img, f"p{i + 1}")
                    att.pages.append(Page(index=i + 1, method="text_layer", text=text,
                                          image_object_id=oid, image_size=size))
                    methods.add("text")
                else:
                    att.pages.append(self._ocr_page(img, i + 1, att))
                    methods.add("ocr")
                self.progress(i + 1, n)
            att.kind = "pdf_text" if methods == {"text"} else "pdf_scanned" if methods == {"ocr"} else "pdf_mixed"
            _drop_repeated_lines(att.pages)
        finally:
            with PDFIUM_LOCK:
                pdf.close()

    # ------------------------------------------------------------ images

    def _image(self, path: Path, att: Attachment) -> None:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((2400, 2400))
            img = np.asarray(im)
        att.kind = "image"
        att.pages.append(self._ocr_page(img, 1, att, is_photo=True))
        self.progress(1, 1)

    def _ocr_page(self, img: np.ndarray, index: int, att: Attachment, is_photo: bool = False) -> Page:
        ocfg, vcfg = self.cfg["ocr"], self.cfg["vision_fallback"]
        pp = ocfg["preprocess"]
        t0 = time.perf_counter()
        clean, skew = preprocess.clean(img, deskew=pp["deskew"], denoise=pp["denoise"], max_skew_deg=pp["max_skew_deg"])
        oid, size = self.store_image(clean, f"p{index}")
        lang = att.language if att.language in ocfg["languages"] else ocfg["default_language"]
        page = Page(index=index, method="ocr", text="", image_object_id=oid, image_size=size, skew_deg=skew)
        try:
            engine = get_engine(lang, ocfg["languages"], ocfg["min_text_score"])
            page.lines = engine.read(clean)
            page.text = lines_to_text(page.lines)
            page.ocr_conf = mean_conf(page.lines)
        except OcrUnavailable as e:
            if lang != "kn":  # Kannada has no OCR model by design; say so once, below
                att.warnings.append(str(e))
        att.timings_ms[f"ocr_p{index}"] = round((time.perf_counter() - t0) * 1000, 1)

        # Second opinion from the vision model when OCR is weak, absent, or the script isn't supported.
        weak = page.ocr_conf is None or page.ocr_conf < vcfg["low_confidence"] or len(page.text) < 20
        if vcfg["enabled"] and (weak or lang == "kn") and self.vision_budget > 0:
            self.vision_budget -= 1
            t1 = time.perf_counter()
            page.vision = transcribe(clean, vcfg["role"], page.text or None, vcfg["disagreement_below"],
                                     LANG_NAMES.get(lang))
            att.timings_ms[f"vision_p{index}"] = round((time.perf_counter() - t1) * 1000, 1)
            if page.vision.error:
                att.warnings.append(f"Page {index}: vision model unavailable ({page.vision.error[:120]})")
            elif not page.text:
                page.text, page.method = page.vision.text, "vision"
            else:
                page.method = "ocr+vision"
                if page.vision.disagrees:
                    att.warnings.append(f"Page {index}: OCR and the vision model disagree "
                                        f"(similarity {page.vision.similarity:.2f}). Check the original.")
        kn_note = "Kannada has no OCR model; text in this document comes from the vision model only."
        if lang == "kn" and kn_note not in att.warnings:
            att.warnings.append(kn_note)
        return page

    # ------------------------------------------------------------ sheets

    def _sheet(self, path: Path, att: Attachment) -> None:
        import pandas as pd

        att.kind = "sheet"
        rows_cap = 5000
        if path.suffix.lower() == ".csv" or att.mime == "text/csv" or att.name.lower().endswith(".csv"):
            frames = {"csv": pd.read_csv(path)}
        else:
            frames = pd.read_excel(path, sheet_name=None, engine="openpyxl")
        for name, df in frames.items():
            df = df.dropna(how="all").dropna(axis=1, how="all")
            prev = df.head(self.cfg["limits"]["table_preview_rows"]).astype(str).values.tolist()
            records = df.head(rows_cap).astype(object).where(df.notna(), None)
            att.tables.append(SheetTable(
                name=str(name), n_rows=len(df), n_cols=df.shape[1], columns=[str(c) for c in df.columns],
                dtypes={str(c): str(t) for c, t in df.dtypes.items()}, preview=prev,
                rows_json=[{str(k): _jsonable(v) for k, v in r.items()} for r in records.to_dict("records")],
            ))
            if len(df) > rows_cap:
                att.warnings.append(f"Sheet {name}: only the first {rows_cap} of {len(df)} rows kept as JSON.")
            # A text rendering so sheets are searchable like any other document.
            header = " | ".join(str(c) for c in df.columns)
            body = "\n".join(" | ".join(str(x) for x in row) for row in df.astype(str).values.tolist()[:500])
            att.pages.append(Page(index=len(att.pages) + 1, method="text_layer",
                                  text=f"Sheet: {name}\n{header}\n{body}"))
        self.progress(1, 1)

    # ------------------------------------------------------------ docx / code / text

    def _docx(self, path: Path, att: Attachment) -> None:
        import docx

        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        att.kind = "docx"
        att.pages.append(Page(index=1, method="text_layer", text="\n".join(parts)[: self.cfg["limits"]["text_max_chars"]]))
        self.progress(1, 1)

    def _textfile(self, path: Path, att: Attachment, kind: str) -> None:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")[: self.cfg["limits"]["text_max_chars"]]
        if kind == "code":
            att.kind = "code"
            att.code.append(CodeFile(path=att.name, size=len(raw), language=CODE_EXT.get(Path(att.name).suffix.lower()),
                                     text=text))
        else:
            att.kind = "text"
        att.pages.append(Page(index=1, method="text_layer", text=text))
        self.progress(1, 1)

    def _zip(self, path: Path, att: Attachment) -> None:
        lim = self.cfg["limits"]
        att.kind = "code"
        budget = lim["code_max_bytes"]
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            if len(infos) > lim["code_max_files"]:
                att.warnings.append(f"Archive has {len(infos)} files; only the first {lim['code_max_files']} are listed.")
            for info in infos[: lim["code_max_files"]]:
                name = info.filename
                if ".." in Path(name).parts or name.startswith("/"):
                    att.warnings.append(f"Skipped unsafe path in archive: {name}")
                    continue
                lang = CODE_EXT.get(Path(name).suffix.lower())
                text = None
                if lang and info.file_size <= budget:
                    try:
                        text = z.read(info).decode("utf-8")
                        budget -= info.file_size
                    except UnicodeDecodeError:
                        text = None
                att.code.append(CodeFile(path=name, size=info.file_size, language=lang, text=text))
        tree = "\n".join(f"{c.path} ({c.size} B)" for c in att.code)
        bodies = "\n\n".join(f"### {c.path}\n{c.text}" for c in att.code if c.text)
        att.pages.append(Page(index=1, method="text_layer", text=f"Files:\n{tree}\n\n{bodies}"))
        self.progress(1, 1)


def _norm(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufffd", "-")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _drop_repeated_lines(pages: list[Page]) -> None:
    """Remove running headers/footers: short lines that appear on most pages of a multi-page PDF.
    Page numbers are normalised first so 'Page 3' and 'Page 4' count as the same line."""
    text_pages = [p for p in pages if p.method == "text_layer"]
    if len(text_pages) < 3:
        return
    def key(s: str) -> str:
        s = s.strip().lower()
        # only page-number lines are collapsed; other lines differing by a number (table rows) stay distinct
        return re.sub(r"\d+", "#", s) if re.search(r"\bpage\s*\d+", s) else s
    counts: dict[str, int] = {}
    for p in text_pages:
        for k in {key(line) for line in p.text.splitlines() if 0 < len(line.strip()) <= 120}:
            counts[k] = counts.get(k, 0) + 1
    boiler = {k for k, n in counts.items() if n >= 0.6 * len(text_pages)}
    for p in text_pages:
        p.text = "\n".join(line for line in p.text.splitlines() if key(line) not in boiler).strip()


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def encode_png(img: np.ndarray) -> bytes:
    buf = io.BytesIO()
    im = Image.fromarray(img)
    if im.mode == "RGB" and _is_gray(img):
        im = im.convert("L")  # scans are grey; halves the PNG size
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _is_gray(img: np.ndarray) -> bool:
    return img.ndim == 3 and bool(np.all(img[..., 0] == img[..., 1])) and bool(np.all(img[..., 1] == img[..., 2]))
