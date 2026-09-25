"""OpenCV clean-up for scans and photos before OCR: denoise, then deskew."""

from __future__ import annotations

import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY if img.shape[2] == 3 else cv2.COLOR_RGBA2GRAY)


def estimate_skew(gray: np.ndarray, max_deg: float = 10.0) -> float:
    """Skew of the text lines in degrees, in the same convention as `rotate`:
    estimate_skew(rotate(page, a)) ~= a, so rotate(img, -estimate_skew(img)) straightens it.

    Text is smeared horizontally into line blobs; the median angle of the long, thin blobs is
    the page skew. Isolated specks never become long blobs, so scan noise doesn't bias it.
    """
    h, w = gray.shape
    scale = 1000 / max(h, w) if max(h, w) > 1000 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1 else gray
    binar = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    binar = cv2.morphologyEx(binar, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))  # drop specks
    blobs = cv2.dilate(binar, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
    contours, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles, weights = [], []
    for c in contours:
        (_, _), (bw, bh), ang = cv2.minAreaRect(c)
        if bw < bh:
            bw, bh = bh, bw
            ang += 90
        if bw < 60 or bw < 5 * bh:  # keep long thin text lines only
            continue
        if ang > 45:
            ang -= 90
        if ang < -45:
            ang += 90
        if abs(ang) <= max_deg:
            angles.append(ang)
            weights.append(bw)
    if not angles:
        return 0.0
    order = np.argsort(angles)
    a, wts = np.asarray(angles)[order], np.asarray(weights)[order]
    return float(a[np.searchsorted(np.cumsum(wts), wts.sum() / 2)])  # length-weighted median


def rotate(img: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate about the centre, keeping the canvas size (white fill)."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle_deg, 1.0)
    border = 255 if img.ndim == 2 else (255, 255, 255)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def clean(img_rgb: np.ndarray, *, deskew: bool = True, denoise: bool = True, max_skew_deg: float = 10.0
          ) -> tuple[np.ndarray, float]:
    """Returns (cleaned RGB image, skew that was removed in degrees)."""
    gray = to_gray(img_rgb)
    if denoise:
        gray = cv2.medianBlur(gray, 3)
    angle = estimate_skew(gray, max_skew_deg) if deskew else 0.0
    if abs(angle) >= 0.15:
        gray = rotate(gray, -angle)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB), round(angle, 2)
