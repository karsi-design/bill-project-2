-- Bill OCR + storage system — Postgres/Supabase schema.
-- Run this once in Supabase's SQL editor (or via POST /api/init-db after deploying).

CREATE TABLE IF NOT EXISTS bills (
    id                   SERIAL PRIMARY KEY,

    vendor_name          TEXT NOT NULL,
    invoice_no           TEXT,
    invoice_date         DATE,
    amount               NUMERIC(14, 2),
    gst_amount           NUMERIC(14, 2),
    currency             TEXT DEFAULT 'INR',
    payment_status       TEXT CHECK (payment_status IN ('paid','unpaid','partially_paid','unknown')) DEFAULT 'unknown',
    payment_date         DATE,
    bank_details         TEXT,
    confidence_notes     TEXT,
    raw_extraction_json  JSONB,

    drive_file_id        TEXT NOT NULL,
    drive_link            TEXT NOT NULL,
    original_filename    TEXT,
    page_count            INTEGER DEFAULT 1,

    uploaded_by            TEXT,
    uploaded_at             TIMESTAMPTZ DEFAULT now(),
    review_status           TEXT CHECK (review_status IN ('pending_review','confirmed','rejected')) DEFAULT 'pending_review',
    confirmed_by             TEXT,
    confirmed_at              TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bill_line_items (
    id            SERIAL PRIMARY KEY,
    bill_id       INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    description   TEXT,
    quantity      NUMERIC,
    unit_price    NUMERIC(14, 2),
    amount        NUMERIC(14, 2)
);

CREATE INDEX IF NOT EXISTS idx_bills_vendor  ON bills (vendor_name);
CREATE INDEX IF NOT EXISTS idx_bills_date    ON bills (invoice_date);
CREATE INDEX IF NOT EXISTS idx_bills_status  ON bills (review_status);
CREATE INDEX IF NOT EXISTS idx_bills_payment ON bills (payment_status);
