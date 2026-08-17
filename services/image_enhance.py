"""Lightweight image enhancement. We deliberately keep this dependency-free
(PIL only, plus the OpenCV that's already a project dependency for the blur
check below) since the heavy lifting -- table/row/cross detection and OCR --
is delegated to the Groq vision model rather than a classical OpenCV pipeline.
This still helps the model read faint handwriting / skewed photos."""
from PIL import Image, ImageOps, ImageEnhance, ExifTags
from pathlib import Path

import cv2

import config
from database.db import get_setting


def enhance_image(src_path: str) -> str:
    img = Image.open(src_path)

    # Respect phone camera EXIF orientation
    try:
        for tag, name in ExifTags.TAGS.items():
            if name == "Orientation":
                orientation_tag = tag
                break
        exif = img._getexif()
        if exif is not None and orientation_tag in exif:
            orientation = exif[orientation_tag]
            rotations = {3: 180, 6: 270, 8: 90}
            if orientation in rotations:
                img = img.rotate(rotations[orientation], expand=True)
    except Exception:
        pass

    img = img.convert("RGB")
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Sharpness(img).enhance(1.5)
    img = ImageEnhance.Contrast(img).enhance(1.15)

    # Downscale so the payload sent to the vision model stays well within its
    # token/rate-limit budget, while keeping resolution high enough to read
    # small handwriting. Vision-LLM token cost scales with pixel count, so
    # this single number is the biggest lever on API cost - 1400px keeps a
    # typical A4 sheet legible while cutting image tokens ~3x versus 2200px.
    max_dim = 1400
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)))

    # JPEG instead of PNG: much smaller payload to upload/base64-encode for
    # the same visible quality, which matters now that request size is a
    # hard rate-limit constraint, not just a nice-to-have.
    out_path = config.PROCESSED_DIR / (Path(src_path).stem + "_enhanced.jpg")
    img.save(out_path, "JPEG", quality=90)
    return str(out_path)


def check_image_quality(image_path: str) -> tuple[bool, str, float]:
    """Cheap local check (no API call) for a photo too blurry/glare-washed
    to read reliably - catches this BEFORE spending a Groq call on a photo
    that was never going to extract well. Uses Laplacian variance (a
    standard, dependency-light blur metric): sharp edges/text produce a
    high variance, a blurry or flat/glare-washed photo produces a low one.

    Returns (is_too_blurry, message, sharpness_score)."""
    img = cv2.imread(image_path)
    if img is None:
        return False, "", 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    threshold = float(get_setting("blur_variance_threshold", 40))
    if variance < threshold:
        return (
            True,
            f"This photo looks too blurry or washed out to read reliably "
            f"(sharpness {variance:.0f}, need at least {threshold:.0f}). "
            f"Please retake it with better focus and lighting.",
            variance,
        )
    return False, "", variance
