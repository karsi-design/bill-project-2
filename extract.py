"""
Same extraction logic as the local version, adapted for serverless:
- Takes raw bytes instead of a file path (no persistent disk to read from).
- Rasterizes PDF pages with PyMuPDF instead of pdf2image/poppler — Vercel's
  Python runtime doesn't have the poppler system binary installed, and
  PyMuPDF ships its own compiled engine inside the pip package, so it
  needs nothing extra installed on the server.
"""
import base64
import io
import json
import os

import pymupdf as fitz  # PyMuPDF — `pymupdf` is the current import name, `fitz` is deprecated
from openai import OpenAI
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
genuine uncertainty in confidence_notes — a reviewer will check it before the bill is confirmed."""


def _image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _bytes_to_images(file_bytes: bytes, filename: str, dpi: int = 200) -> list[Image.Image]:
    if filename.lower().endswith(".pdf"):
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=matrix)
            images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
        return images
    return [Image.open(io.BytesIO(file_bytes))]


def extract_bill(file_bytes: bytes, filename: str, model: str = DEFAULT_MODEL) -> tuple[dict, int]:
    """Returns (extracted_fields_dict, page_count)."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    images = _bytes_to_images(file_bytes, filename)

    content = [
        {"type": "text", "text": f"Extract this bill's data. It has {len(images)} page(s), shown below in order."}
    ]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(img)}})

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_schema", "json_schema": BILL_SCHEMA},
    )
    return json.loads(response.choices[0].message.content), len(images)
