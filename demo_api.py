"""
Exercises every route in api/index.py using Flask's test client, with
db/drive/extract swapped for in-memory fakes (no real Postgres, Drive,
or OpenAI calls — same sandbox limitation as the local-version demos).
Proves the routing, status codes, and response shapes are correct.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent / "api"))

import db  # noqa: E402
import drive  # noqa: E402
import extract  # noqa: E402

_FAKE_BILLS = {}
_NEXT_ID = [1]


def fake_insert_bill(extracted, drive_file_id, drive_link, original_filename, uploaded_by, page_count=1):
    bill_id = _NEXT_ID[0]
    _NEXT_ID[0] += 1
    row = {
        "id": bill_id, **extracted, "drive_file_id": drive_file_id, "drive_link": drive_link,
        "original_filename": original_filename, "uploaded_by": uploaded_by, "page_count": page_count,
        "review_status": "pending_review",
    }
    _FAKE_BILLS[bill_id] = row
    return bill_id


def fake_search_bills(**kwargs):
    return list(_FAKE_BILLS.values())


def fake_get_bill(bill_id):
    return _FAKE_BILLS.get(bill_id)


def fake_get_line_items(bill_id):
    return []


def fake_confirm_bill(bill_id, confirmed_by):
    if bill_id in _FAKE_BILLS:
        _FAKE_BILLS[bill_id]["review_status"] = "confirmed"


def fake_extract_bill(file_bytes, filename, model="gpt-4o-mini"):
    return (
        {"vendor_name": "Saini Electronics", "invoice_no": "SE/117/2026-27", "invoice_date": "2026-04-24",
         "amount": 1100.0, "gst_amount": 167.8, "currency": "INR", "payment_status": "paid",
         "payment_date": "2026-04-24", "bank_details": None, "line_items": [], "confidence_notes": None},
        1,
    )


def fake_upload_bill_bytes(file_bytes, filename, mimetype):
    return "fakeDriveId123", "https://drive.google.com/file/d/fakeDriveId123/view"


db.insert_bill = fake_insert_bill
db.search_bills = fake_search_bills
db.get_bill = fake_get_bill
db.get_line_items = fake_get_line_items
db.confirm_bill = fake_confirm_bill
extract.extract_bill = fake_extract_bill
drive.upload_bill_bytes = fake_upload_bill_bytes

import index as api_module  # noqa: E402  (api/index.py, imported as `index`)

client = api_module.app.test_client()

print("-- POST /api/upload --")
resp = client.post(
    "/api/upload",
    data={"file": (io.BytesIO(b"fake jpeg bytes"), "earpods.jpg"), "uploaded_by": "karan@mittalportfolios.com"},
    content_type="multipart/form-data",
)
print(resp.status_code, resp.get_json())
assert resp.status_code == 200
bill_id = resp.get_json()["id"]

print("\n-- GET /api/bills --")
resp = client.get("/api/bills")
print(resp.status_code, resp.get_json())
assert resp.status_code == 200
assert len(resp.get_json()) == 1

print(f"\n-- GET /api/bills/{bill_id} --")
resp = client.get(f"/api/bills/{bill_id}")
print(resp.status_code, resp.get_json())
assert resp.status_code == 200

print(f"\n-- GET /api/bills/999 (should 404) --")
resp = client.get("/api/bills/999")
print(resp.status_code, resp.get_json())
assert resp.status_code == 404

print(f"\n-- POST /api/confirm --")
resp = client.post("/api/confirm", json={"id": bill_id, "confirmed_by": "karan@mittalportfolios.com"})
print(resp.status_code, resp.get_json())
assert resp.status_code == 200
assert _FAKE_BILLS[bill_id]["review_status"] == "confirmed"

print(f"\n-- POST /api/upload with no file (should 400) --")
resp = client.post("/api/upload", data={}, content_type="multipart/form-data")
print(resp.status_code, resp.get_json())
assert resp.status_code == 400

print("\nAll route checks passed.")
