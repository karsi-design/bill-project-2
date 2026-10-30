"""
All API routes for the bill system, in one Flask app.

Important: Vercel's rewrite in vercel.json replaces the path Flask sees
with the literal destination string ("/api/index.py") -- it does NOT
forward the original request path through PATH_INFO. So instead of
Flask's normal @app.route per endpoint, there's one route matching what
Vercel actually delivers, and the real intended path is read back out
of the `vercel_path` query parameter the rewrite smuggles it through as.
The browser side doesn't need to know any of this -- it still just
fetches '/api/bills' etc. normally; Vercel's rewrite is transparent to it.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from flask import Flask, Response, jsonify, request  # noqa: E402

import db  # noqa: E402
import drive  # noqa: E402
import extract  # noqa: E402
from frontend_html import INDEX_HTML  # noqa: E402

app = Flask(__name__)


def logical_path() -> str:
    return request.args.get("vercel_path", "/")


@app.route("/api/index.py", methods=["GET", "POST"])
def dispatch():
    path = logical_path()
    method = request.method

    if path == "/" and method == "GET":
        return Response(INDEX_HTML, mimetype="text/html")

    if path == "/api/bills" and method == "GET":
        return list_bills()

    m = re.fullmatch(r"/api/bills/(\d+)", path)
    if m and method == "GET":
        return get_bill(int(m.group(1)))

    if path == "/api/upload" and method == "POST":
        return upload()

    if path == "/api/confirm" and method == "POST":
        return confirm()

    if path == "/api/init-db" and method == "POST":
        return init_db_route()

    return jsonify({"error": "not found", "path": path}), 404


def list_bills():
    rows = db.search_bills(
        vendor=request.args.get("vendor"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
        payment_status=request.args.get("payment_status"),
        review_status=request.args.get("review_status"),
        text=request.args.get("q"),
        limit=int(request.args.get("limit", 100)),
    )
    return jsonify(rows)


def get_bill(bill_id):
    bill = db.get_bill(bill_id)
    if not bill:
        return jsonify({"error": "not found"}), 404
    bill["line_items"] = db.get_line_items(bill_id)
    return jsonify(bill)


def upload():
    if "file" not in request.files:
        return jsonify({"error": "no file field in form data"}), 400

    f = request.files["file"]
    uploaded_by = request.form.get("uploaded_by", "unknown")
    file_bytes = f.read()

    try:
        extracted, n_pages = extract.extract_bill(file_bytes, f.filename)
    except Exception as e:
        return jsonify({"error": f"extraction failed: {e}"}), 502

    try:
        drive_file_id, drive_link = drive.upload_bill_bytes(file_bytes, f.filename, f.mimetype)
    except Exception as e:
        return jsonify({"error": f"drive upload failed: {e}"}), 502

    bill_id = db.insert_bill(
        extracted, drive_file_id, drive_link, f.filename, uploaded_by, page_count=n_pages
    )
    return jsonify({"id": bill_id, "review_status": "pending_review", "extracted": extracted})


def confirm():
    data = request.get_json(force=True)
    if "id" not in data:
        return jsonify({"error": "missing id"}), 400
    db.confirm_bill(data["id"], data.get("confirmed_by", "unknown"))
    return jsonify({"ok": True})


def init_db_route():
    """Call this once, right after your first deploy, to create the tables. Safe to call again."""
    db.init_db()
    return jsonify({"ok": True})