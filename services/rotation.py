"""
Straightens small tilts (a few degrees) in a photographed order sheet.

This used to also detect gross 90/180/270 rotation via a second Groq API
call. That call is gone: it doubled our request count against Groq's
per-minute token budget on every single image (and, being a "cheap" call
with a small max_tokens, was the first thing to fail outright once the
model's reasoning traces ate its token allowance). Gross rotation is now
handled two ways instead, at zero extra API cost in the common case:

1. EXIF orientation - handled already in image_enhance.enhance_image() for
   any photo that has it (the vast majority of phone camera shots).
2. For the rare image with no/incorrect EXIF that still comes in sideways,
   groq_vision.extract_document() itself reports whether it had to read the
   sheet rotated, as one extra field on the SAME call that already reads
   the whole document - no separate request. processor.py acts on that by
   rotating locally and re-extracting once, only when actually needed.

What's left here is a local, dependency-light OpenCV estimate of small-angle
skew (a photo held a few degrees off-level) from the dominant near-horizontal
line angle in the image. No network call, no tokens, no rate limit.
"""
import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import config

logger = logging.getLogger(__name__)


def _opencv_fine_skew(image_path: str) -> float:
    """Estimate small-angle skew (no 90/180/270 correction) from the
    dominant near-horizontal line angle in the image - works well on ruled
    tables even without reading any text."""
    img = cv2.imread(image_path)
    if img is None:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=120, minLineLength=img.shape[1] // 4, maxLineGap=20
    )
    if lines is None:
        return 0.0

    angles = []
    for line in lines:
        coords = np.array(line).reshape(-1)
        x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Only consider near-horizontal lines (table rows / rulings), reject
        # near-vertical ones (table column dividers) to avoid skewing the estimate
        if abs(angle) < 20:
            angles.append(angle)

    if not angles:
        return 0.0
    median_angle = float(np.median(angles))
    return max(-15.0, min(15.0, median_angle))


def correct_orientation(image_path: str) -> str:
    """Returns the path to a (possibly new) deskewed image ready for
    extraction. If no correction is needed, returns the original path."""
    if not config.AUTO_ROTATE_ENABLED:
        return image_path

    try:
        fine = _opencv_fine_skew(image_path)
    except Exception as e:
        logger.warning("OpenCV skew estimate failed (%s) - using image as-is", e)
        return image_path

    if abs(fine) < 0.5:
        return image_path  # already straight enough, skip re-encoding

    img = Image.open(image_path).convert("RGB")
    # PIL's rotate() is counter-clockwise for positive angles; our estimate
    # is clockwise degrees, so negate.
    rotated = img.rotate(-fine, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)

    out_path = str(config.PROCESSED_DIR / (Path(image_path).stem + "_deskewed.jpg"))
    rotated.save(out_path, "JPEG", quality=90)
    return out_path


def rotate_90_steps(image_path: str, clockwise_degrees: int) -> str:
    """Rotates the image by a multiple of 90 degrees (0/90/180/270),
    used when groq_vision reports the sheet was photographed sideways."""
    clockwise_degrees = int(round(clockwise_degrees / 90.0)) * 90 % 360
    if clockwise_degrees == 0:
        return image_path
    img = Image.open(image_path).convert("RGB")
    rotated = img.rotate(-clockwise_degrees, expand=True, fillcolor=(255, 255, 255))
    out_path = str(config.PROCESSED_DIR / (Path(image_path).stem + f"_rot{clockwise_degrees}.jpg"))
    rotated.save(out_path, "JPEG", quality=90)
    return out_path
