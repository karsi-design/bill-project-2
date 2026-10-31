"""
Bill field extraction via the OpenAI API, using Structured Outputs so the
response is always valid JSON matching BILL_SCHEMA — no regex-parsing of
free-text model output, no silently-malformed fields.

Cost note: defaults to gpt-4o-mini. This is a bounded extraction task
(read the fields off a page image), not open-ended reasoning, so the
mini tier is the right fit — check OpenAI's current pricing page before
running this at volume, rates change.
"""
import base64
import io
import json
import os
from pathlib import Path

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image

DEFAULT_MODEL = "gpt-4o-mini"

BILL_SCHEMA = {
    "name": "bill_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "vendor_name": {
                "type": "string",
                "description": "The issuing company or person's name, as printed on the bill letterhead.",
            },
            "invoice_no": {"type": ["string", "null"]},
            "invoice_date": {
                "type": ["string", "null"],
                "description": "ISO 8601 date (YYYY-MM-DD). Convert from whatever format is printed.",
            },
            "amount": {
                "type": ["number", "null"],
                "description": "The final net/total payable amount (after tax, after any round-off).",
            },
            "gst_amount": {"type": ["number", "null"], "description": "Total CGST+SGST or IGST, if shown."},
            "currency": {"type": "string", "default": "INR"},
            "payment_status": {
                "type": "string",
                "enum": ["paid", "unpaid", "partially_paid", "unknown"],
                "description": "Infer from any 'Paid' stamp, signature-over-amount, or explicit hold/pending note.",
            },
            "payment_date": {
                "type": ["string", "null"],
                "description": "ISO 8601 date, if a payment date is handwritten or stamped on the bill.",
            },
            "bank_details": {
                "type": ["string", "null"],
                "description": "Bank name + account number + IFSC, as printed, concatenated into one string.",
            },
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "quantity": {"type": ["number", "null"]},
                        "unit_price": {"type": ["number", "null"]},
                        "amount": {"type": ["number", "null"]},
                    },
                    "required": ["description", "quantity", "unit_price", "amount"],
                    "additionalProperties": False,
                },
            },
            "confidence_notes": {
                "type": ["string", "null"],
                "description": (
                    "Anything handwritten, stamped, smudged, or otherwise uncertain that a human "
                    "reviewer should double-check before confirming this bill."
                ),
            },
        },
        "required": [
            "vendor_name", "invoice_no", "invoice_date", "amount", "gst_amount", "currency",
            "payment_status", "payment_date", "bank_details", "line_items", "confidence_notes",
        ],
        "additionalProperties": False,
    },
}

EXTRACTION_PROMPT = """You are extracting structured data from a photographed or scanned business \
bill/invoice. Read ALL text carefully — printed text, handwritten notes, rubber stamps, and \
signatures. Indian business bills commonly have a handwritten "Paid on <date>" note or a signature \
scrawled across the amount to mark it paid; treat these as authoritative for payment_status and \
payment_date even when the rest of the bill is machine-printed.

If the bill spans multiple pages/images, treat them as one document (continuation pages, duplicate \
copies, or a bill with its payment stub on a second page).

If a field genuinely is not present on the bill, return null for it rather than guessing. Note any \
genuine uncertainty in confidence_notes — a reviewer will check it before the bill is confirmed.

If this document is a dense statement or ledger with many individual transaction rows (more than ~25) \
rather than a normal vendor bill with a handful of line items, do NOT itemize every single row — that \
produces a response too long to complete. Instead return at most 25 representative or summary line \
items (e.g. grouped by category or date range), and note in confidence_notes that the document had more \
line items than are listed and a reviewer should refer to the original file in Drive for the full detail."""


MAX_IMAGE_DIMENSION = 2000  # px, longest side


def _resize_if_needed(img: Image.Image, max_dim: int = MAX_IMAGE_DIMENSION) -> Image.Image:
    """
    Some source documents (e.g. report-generator PDFs sized for wide
    landscape printing) have physical page dimensions far larger than
    their actual content needs. Rendered at a normal DPI, those become
    huge, mostly-blank images — which has been observed to make the
    vision model produce degenerate, truncated output instead of clean
    JSON. Capping the longest side keeps every image a sane, consistent
    size regardless of the source page's physical dimensions.
    """
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    scale = max_dim / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def _load_as_images(path: str | Path, dpi: int = 200) -> list[Image.Image]:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return [_resize_if_needed(img) for img in convert_from_path(str(path), dpi=dpi)]
    return [_resize_if_needed(Image.open(path))]


def extract_bill(
    file_path: str | Path,
    model: str = DEFAULT_MODEL,
    client: OpenAI | None = None,
) -> tuple[dict, int]:
    """
    Extract structured fields from a bill file (image or PDF, any page count).
    Returns (extracted_fields_dict, page_count). Raises on API error or on a
    truncated/malformed response — callers should catch and route the upload
    to the review queue as a failed-extraction case rather than losing it.
    """
    client = client or OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    images = _load_as_images(file_path)

    content = [{"type": "text", "text": "Extract this bill's data. It has "
                                         f"{len(images)} page(s), shown below in order."}]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(img)}})

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_schema", "json_schema": BILL_SCHEMA},
        max_tokens=8000,
    )
    raw = response.choices[0].message.content
    try:
        return json.loads(raw), len(images)
    except json.JSONDecodeError as e:
        finish_reason = response.choices[0].finish_reason
        if finish_reason == "length":
            raise RuntimeError(
                "OpenAI's response was cut off before finishing (hit the output length limit) — "
                "likely a document with too many transaction rows for one extraction. "
                f"Got {len(raw)} characters before truncation."
            ) from e
        raise RuntimeError(f"OpenAI returned malformed JSON (not a truncation issue): {e}") from e