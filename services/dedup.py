"""
Duplicate-upload detection, so re-uploading the same order sheet doesn't
create a second order and doesn't waste a Groq call.

Two layers, deliberately combined so neither genuine duplicates nor
genuine new photos get mishandled:

1. Exact re-upload - SHA-256 of the raw file bytes. Catches a literal
   re-upload of the same file with zero ambiguity, before any processing.
2. Near-duplicate re-photo - a perceptual hash (dHash) computed on the
   enhanced/normalized image, so a slightly different angle, crop, or
   lighting of the same physical sheet still matches. Implemented with
   Pillow only (no new dependency): resize to 9x8 grayscale, compare each
   pixel to its right neighbour -> one bit per comparison -> 64-bit hash.
   The Hamming-distance threshold is kept deliberately tight so a
   genuinely different sheet is never mistaken for a repeat - when in
   doubt, this lets a new photo through rather than blocking it.
"""
import hashlib
from PIL import Image

DHASH_SIZE = 8  # -> 64-bit hash
NEAR_DUP_MAX_DISTANCE = 6  # out of 64 bits - tight on purpose


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash(image_path: str) -> str:
    img = Image.open(image_path).convert("L").resize((DHASH_SIZE + 1, DHASH_SIZE))
    pixels = list(img.getdata())
    width = DHASH_SIZE + 1
    bits = []
    for row in range(DHASH_SIZE):
        row_pixels = pixels[row * width:(row + 1) * width]
        for col in range(DHASH_SIZE):
            bits.append(1 if row_pixels[col] < row_pixels[col + 1] else 0)
    value = 0
    for b in bits:
        value = (value << 1) | b
    return format(value, "016x")


def hamming_distance(hash_a: str, hash_b: str) -> int:
    if not hash_a or not hash_b:
        return 999
    try:
        return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")
    except ValueError:
        return 999


def is_near_duplicate(hash_a: str, hash_b: str) -> bool:
    return hamming_distance(hash_a, hash_b) <= NEAR_DUP_MAX_DISTANCE
