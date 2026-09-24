"""PNG thumbnails for images and the first page of PDFs (pypdfium2, never PyMuPDF)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)


def make_thumbnail(src: Path, mime: str, max_px: int) -> bytes | None:
    try:
        if mime.startswith("image/") and mime != "image/svg+xml":
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                return _to_png(im, max_px)
        if mime == "application/pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(src))
            try:
                page = pdf[0]
                w, h = page.get_size()
                scale = (max_px * 2) / max(w, h, 1)
                im = page.render(scale=scale).to_pil()
                page.close()
                return _to_png(im, max_px)
            finally:
                pdf.close()
    except Exception as exc:  # thumbnails are best effort; never fail the upload
        log.warning("thumbnail failed for %s (%s): %s", src.name, mime, exc)
    return None


def _to_png(im: Image.Image, max_px: int) -> bytes:
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
