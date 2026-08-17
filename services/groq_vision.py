"""
Calls a Groq-hosted vision-language model to read a retailer order sheet
and return:
  1. document-level fields - retailer ("M/s.") name, the order date printed
     in the top-right corner, and whether the photo needs a 90/180/270
     rotation to be readable
  2. ONLY the rows that are hand-marked with a cross (X) - i.e. the
     products that could not be supplied.

Model: qwen/qwen3.6-27b is currently the only vision-capable model Groq
serves (Llama 4 Scout/Maverick are deprecated or half-quota on this
account's tier), so it's the right choice - the fix below is about calling
it correctly, not switching models.

--- Why requests were failing (413 "Request too large") ---
qwen3.6-27b is a *reasoning* model: by default it "thinks" in a long
<think> block before answering, and those thinking tokens are billed
against the same per-minute token budget as everything else. Combined with
a large, high-resolution image, a single request could easily ask for
10,000+ tokens against an 8,000 TPM account limit - a hard cap that no
amount of retrying fixes, only sending a smaller request does.

Three changes fix this permanently:
  1. reasoning_format="hidden" + reasoning_effort="none" - turns off the
     visible thinking trace entirely (Qwen3's supported "non-thinking
     mode"), which was the single biggest token cost.
  2. The image itself is now sent smaller (see image_enhance.py - 1400px
     longest side, JPEG). Vision-LLM token cost scales with pixel count,
     so this is the second biggest lever.
  3. max_tokens is sized for "a short JSON object", not "a full reasoning
     trace" (a few thousand, not 8192).
  4. Orientation is reported as one extra field on this SAME call instead
     of a separate request (see rotation.py) - halves the request count
     for the common case where no rotation is needed.

On top of that, _call_with_retry below automatically recovers from the two
transient failure modes Groq can still return:
  - 429 rate limit -> wait (honoring Retry-After if present) and retry.
  - 413 request too large -> shrink the image further and retry once,
    rather than just failing outright.
"""
import base64
import io
import json
import re
import time
import logging

from groq import Groq
from groq import APIStatusError
from PIL import Image

import config
from database.db import get_setting

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert document-extraction engine specialized in reading \
handwritten retailer order sheets from an auto-parts / retail business in India.

======================================================================
STEP 1 - IS THE PHOTO ROTATED?
======================================================================
- rotate_clockwise_degrees: if the sheet is sideways or upside-down in this \
image (e.g. you have to tilt your head to read it), report how many degrees \
to rotate the image CLOCKWISE so the table rows become horizontal and \
readable left-to-right, top-to-bottom. Must be one of: 0, 90, 180, 270. \
Most photos are already upright - only report non-zero if it is clearly rotated.

If non-zero, still do your best on steps 2-4 below reading the content as \
oriented in the image; a corrected pass will follow.

======================================================================
STEP 2 - DOCUMENT HEADER FIELDS
======================================================================
Near the top of the sheet, extract:

- retailer_name: the party/retailer name, printed after a label such as \
"M/s.", "M/s :", "Party", or similar (e.g. "NATIONAL AUTO PARTS"). Return \
just the name, without the "M/s." label itself. If genuinely not present \
anywhere on the sheet, return "".
- order_date: the date printed in the TOP-RIGHT corner of the sheet, next \
to a label such as "Date". Return it EXACTLY as printed, digits and \
separators as-is (e.g. "15/08/2026"). Do not reformat, reorder, or \
reinterpret it. If genuinely not present, return "".

======================================================================
STEP 3 - THE TABLE
======================================================================
The sheet is a table with columns similar to (column names vary by retailer):
Sr. | Product Alias | Product Location | Qty | Closing Qty | MRP

Product Alias is an alphanumeric code, often with dashes, e.g. "53172-K0P-DA0", \
and is unique per product - it is usually handwritten/underlined/printed in \
the second column, immediately after the Sr. number.

======================================================================
STEP 4 - CLASSIFYING THE HANDWRITTEN MARK ON EACH ROW
======================================================================
Go through the table ONE ROW AT A TIME, in order by Sr. number, starting from \
Sr. 1 and not skipping any row. For every single row, look closely at the space \
around the Sr. number and the Product Alias and decide which of these marks (if \
any) is present. Only one type applies per row:

(a) CROSS / X-MARK - two distinct strokes crossing each other at an angle, \
forming an "X" shape, drawn over or immediately beside the Sr. number and/or \
the Product Alias. This is the ONLY mark that means the product was NOT \
AVAILABLE / could not be supplied. A cross can vary in size and neatness - \
it may be small and tight or large and loose - but it always has TWO strokes \
that cross each other. THESE are the rows you must extract.

(b) TICK / CHECKMARK (✓) - a single "V"-shaped or checkmark stroke, with no \
second crossing stroke. Means available. IGNORE.

(c) FILLED DOT / BULLET / SMALL BLOB (•) placed next to the Sr. number - a \
small solid circular mark, not two crossing lines. IGNORE.

(d) STRIKETHROUGH LINE - a single straight or slightly curved line drawn \
THROUGH the printed text of the Product Alias (cancelling/replacing that \
line item), with no second crossing stroke forming an X. IGNORE - this is a \
correction/cancellation mark, not an unavailability cross.

(e) NO MARK AT ALL - the row is untouched. IGNORE.

Do not confuse (a) with (b), (c), (d), or (e). The deciding test for a true \
cross is: "are there two strokes that cross each other, forming an X shape?" \
If you only see one stroke of any kind (straight, curved, checkmark-shaped), \
it is NOT a cross, no matter how messy it looks - do not include that row.

Check each row against this test individually before deciding; do not judge \
the sheet at a glance. Only report a row in the final output once you are \
confident it is case (a).

======================================================================
STEP 5 - OUTPUT
======================================================================
For every row you determine is X-marked (case (a) only), extract:
- row_sr_no: the Sr. number of that row as printed (string)
- product_alias: the alias exactly as written, preserving dashes/case as best you can read them
- required_quantity: the numeric value from the Qty column for that row (number)
- raw_row_text: everything else legible on that row (location, closing qty, mrp) as one string
- ocr_confidence: your confidence 0.0-1.0 that product_alias and required_quantity were read correctly
- cross_confidence: your confidence 0.0-1.0 that this row is genuinely X-marked (case (a)), not a tick/dot/strikethrough/blank

Return STRICT JSON ONLY, no prose, no markdown fences, in this exact shape:
{"rotate_clockwise_degrees": 0, "retailer_name": "NATIONAL AUTO PARTS", "order_date": "15/08/2026", \
"rows": [{"row_sr_no": "5", "product_alias": "53172-K0P-DA0", "required_quantity": 1000, \
"raw_row_text": "A147 1000 2 2.00", "ocr_confidence": 0.92, "cross_confidence": 0.95}]}

If there are no X-marked rows, return an empty "rows" list. Never invent rows, a \
retailer name, or an order date that are not actually on the sheet.
"""

MAX_ATTEMPTS = 4
INITIAL_MAX_DIM = 1400
INITIAL_MAX_TOKENS = 3000


class GroqVisionError(RuntimeError):
    pass


def _encode_image(path: str, max_dim: int, quality: int) -> str:
    """Re-encodes the image at the given size/quality for this attempt.
    Shrinking is applied on top of whatever image_enhance.py already
    produced, so a 413 retry can go smaller without touching the file
    used for the review-page thumbnail."""
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _get_client() -> Groq:
    api_key = config.GROQ_API_KEY or get_setting("groq_api_key", "")
    if not api_key:
        raise GroqVisionError(
            "No Groq API key configured. Add GROQ_API_KEY to your .env file "
            "or set it on the Settings page."
        )
    return Groq(api_key=api_key)


def _strip_to_json(text: str) -> dict:
    """Vision models sometimes wrap JSON in ```json fences, leak <think>...</think>
    reasoning into the visible content, or add other stray text."""
    text = text.strip()
    # Defensive: if a <think> block leaked through despite reasoning_format="hidden"
    # (e.g. the model was switched to one that ignores that param), drop it.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def _call_with_retry(client: Groq, model: str, image_path: str, prompt_text: str) -> tuple[str, int]:
    """Runs the chat completion, automatically recovering from the two
    transient Groq failure modes: rate limiting (429) and request-too-large
    (413). Everything else is raised immediately. Returns (content, total_tokens_used)."""
    max_dim = INITIAL_MAX_DIM
    quality = 88
    max_tokens = INITIAL_MAX_TOKENS
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        b64 = _encode_image(image_path, max_dim, quality)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    },
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                # Non-thinking mode: no <think> trace generated at all, which is
                # both cheaper (fits our TPM budget) and faster. reasoning_format
                # is kept as a belt-and-suspenders in case a future model on this
                # slug still emits a trace despite reasoning_effort="none".
                reasoning_effort="none",
                reasoning_format="hidden",
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise GroqVisionError("Empty response from vision model")
            tokens_used = 0
            try:
                tokens_used = int(response.usage.total_tokens)
            except Exception:
                pass
            return content, tokens_used

        except APIStatusError as e:
            last_error = e
            status = e.status_code
            body_msg = str(getattr(e, "message", "") or str(e))

            if status == 429:
                retry_after = None
                try:
                    retry_after = float(e.response.headers.get("retry-after", ""))
                except Exception:
                    pass
                wait = retry_after if retry_after else min(2 ** attempt, 20)
                logger.warning(
                    "Groq rate limited (attempt %d/%d) - waiting %.1fs", attempt, MAX_ATTEMPTS, wait
                )
                time.sleep(wait)
                continue

            if status == 413 or "too large" in body_msg.lower() or "reduce your message size" in body_msg.lower():
                # Shrink harder each retry: smaller image, lower quality, less
                # room reserved for the answer.
                max_dim = int(max_dim * 0.65)
                quality = max(60, quality - 15)
                max_tokens = max(1200, int(max_tokens * 0.7))
                logger.warning(
                    "Groq request too large (attempt %d/%d) - retrying at max_dim=%d, "
                    "quality=%d, max_tokens=%d",
                    attempt, MAX_ATTEMPTS, max_dim, quality, max_tokens,
                )
                continue

            # Anything else (auth, bad request, server error) - no point retrying blindly.
            raise GroqVisionError(f"Groq API call failed: {e}") from e

        except Exception as e:
            last_error = e
            raise GroqVisionError(f"Groq API call failed: {e}") from e

    raise GroqVisionError(
        f"Groq API call kept failing after {MAX_ATTEMPTS} attempts even after shrinking "
        f"the request. Last error: {last_error}"
    )


def extract_document(image_path: str) -> dict:
    """Returns {"retailer_name": str, "order_date": str,
    "rotate_clockwise_degrees": int, "tokens_used": int, "rows": [...]} for
    one order sheet image. `rows` contains only the X-marked (unavailable)
    line items."""
    client = _get_client()
    model = get_setting("groq_model", config.GROQ_MODEL_DEFAULT)

    raw_text, tokens_used = _call_with_retry(
        client,
        model,
        image_path,
        "Extract the retailer name, the order date (top-right corner), whether the "
        "photo needs rotating, and every X-marked (unavailable) row from this order "
        "sheet. Go row by row, Sr. 1 onward, and do not skip any row.",
    )

    try:
        parsed = _strip_to_json(raw_text)
    except Exception as e:
        raise GroqVisionError(
            f"Could not parse model response as JSON: {e}\nRaw response: {raw_text[:500]}"
        ) from e

    retailer_name = str(parsed.get("retailer_name", "") or "").strip()
    order_date = str(parsed.get("order_date", "") or "").strip()
    try:
        rotate = int(round(float(parsed.get("rotate_clockwise_degrees", 0) or 0) / 90.0)) * 90 % 360
    except (TypeError, ValueError):
        rotate = 0

    rows = parsed.get("rows", [])
    cleaned = []
    for r in rows:
        alias = str(r.get("product_alias", "")).strip()
        if not alias:
            continue
        try:
            qty = float(r.get("required_quantity", 0) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        cleaned.append(
            {
                "row_sr_no": str(r.get("row_sr_no", "")).strip(),
                "product_alias": alias,
                "required_quantity": qty,
                "raw_row_text": str(r.get("raw_row_text", "")).strip(),
                "ocr_confidence": float(r.get("ocr_confidence", 0) or 0),
                "cross_confidence": float(r.get("cross_confidence", 0) or 0),
            }
        )

    return {
        "retailer_name": retailer_name,
        "order_date": order_date,
        "rotate_clockwise_degrees": rotate,
        "tokens_used": tokens_used,
        "rows": cleaned,
    }


def extract_crossed_rows(image_path: str) -> list[dict]:
    """Back-compat wrapper - returns just the row list."""
    return extract_document(image_path)["rows"]
