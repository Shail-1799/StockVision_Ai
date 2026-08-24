"""Lightweight image enhancement. We deliberately keep this dependency-free
(PIL only, plus the OpenCV that's already a project dependency for the blur
check below) since the heavy lifting -- table/row/cross detection and OCR --
is delegated to the Groq vision model rather than a classical OpenCV pipeline.
This still helps the model read faint handwriting / skewed photos.

Memory note (Render free tier is 512MB total): every function here explicitly
closes/deletes large image buffers as soon as it's done with them instead of
letting them sit until Python's garbage collector gets around to it, and cv2
is imported lazily so a request that never processes an image doesn't pay for
it. See processor.py for the gc.collect() called after each upload."""
from PIL import Image, ImageOps, ImageEnhance, ExifTags
from pathlib import Path
import os

import config
from database.db import get_setting

# Longest-side pixel cap for the image actually sent to the vision model.
# Lower = less memory per request AND fewer vision tokens (see groq_vision.py),
# at some cost to legibility of very small handwriting. Override with the
# MAX_IMAGE_DIM env var without a code change if 512MB is still tight.
MAX_IMAGE_DIM = int(os.environ.get("MAX_IMAGE_DIM", "1300"))


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
                rotated = img.rotate(rotations[orientation], expand=True)
                img.close()
                img = rotated
    except Exception:
        pass

    converted = img.convert("RGB")
    if converted is not img:
        img.close()
    img = converted

    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Sharpness(img).enhance(1.5)
    img = ImageEnhance.Contrast(img).enhance(1.15)

    # Downscale so the payload sent to the vision model stays well within its
    # token/rate-limit budget (and well within the server's own memory
    # budget), while keeping resolution high enough to read small
    # handwriting. Vision-LLM token cost scales with pixel count.
    if max(img.size) > MAX_IMAGE_DIM:
        ratio = MAX_IMAGE_DIM / max(img.size)
        resized = img.resize((int(img.width * ratio), int(img.height * ratio)))
        img.close()
        img = resized

    # JPEG instead of PNG: much smaller payload to upload/base64-encode for
    # the same visible quality, which matters now that request size is a
    # hard rate-limit constraint, not just a nice-to-have.
    out_path = config.PROCESSED_DIR / (Path(src_path).stem + "_enhanced.jpg")
    img.save(out_path, "JPEG", quality=90)
    img.close()
    return str(out_path)


def check_image_quality(image_path: str) -> tuple[bool, str, float]:
    """Cheap local check (no API call) for a photo too blurry/glare-washed
    to read reliably - catches this BEFORE spending a Groq call on a photo
    that was never going to extract well. Uses Laplacian variance (a
    standard, dependency-light blur metric): sharp edges/text produce a
    high variance, a blurry or flat/glare-washed photo produces a low one.

    Returns (is_too_blurry, message, sharpness_score)."""
    import cv2  # lazy: only paid for by requests that actually check quality

    img = cv2.imread(image_path)
    if img is None:
        return False, "", 0.0
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    finally:
        del img
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
