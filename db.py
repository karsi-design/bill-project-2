"""
Postgres (Supabase) access layer — the networked replacement for the
local SQLite db.py, since Vercel's serverless functions can't rely on a
file persisting on disk between requests.

Needs DATABASE_URL set (Supabase gives you this connection string under
Project Settings -> Database -> Connection string -> URI).
"""
import json
import os
from pathlib import Path

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("Set DATABASE_URL to your Supabase Postgres connection string.")
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db() -> None:
    """One-time setup — safe to call more than once (CREATE TABLE IF NOT EXISTS)."""
    schema_path = Path(__file__).parent.parent / "schema_postgres.sql"
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(schema_path.read_text())
    finally:
        conn.close()


def insert_bill(
    extracted: dict,
    drive_file_id: str,
    drive_link: str,
    original_filename: str,
    uploaded_by: str,
    page_count: int = 1,
) -> int:
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bills (
                    vendor_name, invoice_no, invoice_date, amount, gst_amount, currency,
                    payment_status, payment_date, bank_details, confidence_notes,
                    raw_extraction_json, drive_file_id, drive_link, original_filename,
                    page_count, uploaded_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    extracted.get("vendor_name"),
                    extracted.get("invoice_no"),
                    extracted.get("invoice_date"),
                    extracted.get("amount"),
                    extracted.get("gst_amount"),
                    extracted.get("currency") or "INR",
                    extracted.get("payment_status") or "unknown",
                    extracted.get("payment_date"),
                    extracted.get("bank_details"),
                    extracted.get("confidence_notes"),
                    json.dumps(extracted),
                    drive_file_id,
                    drive_link,
                    original_filename,
                    page_count,
                    uploaded_by,
                ),
            )
            bill_id = cur.fetchone()["id"]
            for li in extracted.get("line_items") or []:
                cur.execute(
                    """INSERT INTO bill_line_items (bill_id, description, quantity, unit_price, amount)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (bill_id, li.get("description"), li.get("quantity"), li.get("unit_price"), li.get("amount")),
                )
            return bill_id
    finally:
        conn.close()


def confirm_bill(bill_id: int, confirmed_by: str) -> None:
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE bills SET review_status = 'confirmed', confirmed_by = %s, confirmed_at = now()
                   WHERE id = %s""",
                (confirmed_by, bill_id),
            )
    finally:
        conn.close()


def search_bills(
    vendor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    payment_status: str | None = None,
    review_status: str | None = None,
    text: str | None = None,
    limit: int = 100,
) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT * FROM bills WHERE 1=1"
        params: list = []
        if vendor:
            query += " AND vendor_name ILIKE %s"
            params.append(f"%{vendor}%")
        if date_from:
            query += " AND invoice_date >= %s"
            params.append(date_from)
        if date_to:
            query += " AND invoice_date <= %s"
            params.append(date_to)
        if payment_status:
            query += " AND payment_status = %s"
            params.append(payment_status)
        if review_status:
            query += " AND review_status = %s"
            params.append(review_status)
        if text:
            query += " AND (vendor_name ILIKE %s OR invoice_no ILIKE %s)"
            params += [f"%{text}%", f"%{text}%"]
        query += " ORDER BY invoice_date DESC NULLS LAST, id DESC LIMIT %s"
        params.append(limit)

        with conn, conn.cursor() as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_bill(bill_id: int) -> dict | None:
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM bills WHERE id = %s", (bill_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_line_items(bill_id: int) -> list[dict]:
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM bill_line_items WHERE bill_id = %s", (bill_id,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
