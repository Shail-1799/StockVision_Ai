# StockVision AI

Inventory shortage manager for retailer order sheets. Upload a photographed
or scanned order sheet (from a phone or a desktop), it finds every row
hand-marked with a cross (X - meaning "not available"), reads the Product
Alias + Quantity for those rows only, auto-corrects rotated/tilted photos
first, and aggregates shortages across every upload into a ready-to-use next
purchase order (Excel export). Every extracted field is editable afterwards,
Excel-style, and you can also type in shortages manually.

## What's new in this version

1. Duplicate detection
2. Bulk upload with live progress
3. Lightweight multi-user (name picker, no passwords)
4. Dashboard overhaul — shared chart theme (components/charts.py), OCR-confidence histogram, recurring-shortages table, restyled existing charts.
5. Side-by-side photo verify	Orders detail + All Records row-select
6. Bulk retry failed uploads	Orders page, new panel
7. roq usage tracking	Insights page
8. Undo last edit	All Records
9. Reorder alerts	Dashboard + Missing Products flag
10. Retailer reliability report	Insights page
11. MOQ-aware export	Reports (also fixed: export now actually downloads to your browser instead of just reporting a server path — that was silently broken for anyone not on the same machine as the server)
12.	Blur/glare pre-check	Before every Groq call

### Run locally

```bash
python -m venv venv
source venv/bin/activate      # venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env          # edit .env, add GROQ_API_KEY
python app.py
```

## How extraction works

Each image goes through: enhance (contrast/orientation-EXIF fix) → **auto
rotate/deskew** → Groq vision extraction (given your exact table layout and
what a cross vs. tick/dot looks like, returns Product Alias + Qty + its own
confidence scores per row) → validation against your optional Product
Master list → saved to the database. Rows below your confidence thresholds
land in the **Review Queue** instead of being auto-accepted, so nothing
questionable silently pollutes your totals - you (or now, direct spreadsheet
edits in **All Records**) decide.

## Project layout

```
app.py                     Dash entrypoint, page registration, mobile meta tags
wsgi.py                    Vercel/production WSGI entrypoint
vercel.json                Vercel deployment config
config.py                  Paths, env vars, serverless + Postgres/SQLite switch
database/
    models.py               SQLAlchemy schema
    db.py                    Engine/session + settings store
services/
    image_enhance.py         PIL-based orientation/contrast fix
    rotation.py               AI-based rotate/deskew + OpenCV fallback (NEW)
    pdf_utils.py              PDF -> per-page PNG (PyMuPDF, no system deps)
    groq_vision.py            The core cross-detection + OCR call to Groq
    validator.py              Regex + product-master fuzzy validation
    processor.py              Orchestrates one upload end-to-end
    aggregator.py             All aggregation/dashboard/review/edit queries (NEW: edit/manual-add/delete)
    exporter.py                Excel (Summary + Detailed History) export
    product_master_import.py   CSV/Excel product master importer
pages/                      Dashboard, Upload (camera+gallery), Orders (editable),
                             Missing Products, All Records (NEW, editable+manual),
                             Review Queue, Reports, Settings
components/navbar.py        Responsive collapsible nav bar
assets/
    mobile_capture.js         Patches camera capture onto the Upload widget (NEW)
    manifest.json              Add-to-home-screen support (NEW)
    style.css                  Incl. mobile responsive tweaks
```

## Notes / assumptions

- The PRD's suggested frontend stack was Dash + Dash Mantine Components; I
  used Dash + dash-bootstrap-components + dash-ag-grid instead for a more
  predictable "just works" build.
- PDF pages are converted to images with PyMuPDF (pure Python, no Poppler
  install needed).
- "Aggregated Products" is computed live via a `GROUP BY` query rather than
  a separately-maintained table, so it can never drift out of sync.
- On Vercel, original photos are processed and then discarded (not
  permanently stored) - only extracted rows persist, in Postgres. Say the
  word if you want photo retention added via Vercel Blob/S3.
- Camera capture (the `capture="environment"` HTML attribute) is applied via
  a small JS patch since Dash's `dcc.Upload` doesn't expose it directly -
  works on Android Chrome and iOS Safari.