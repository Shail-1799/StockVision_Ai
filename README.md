# StockVision AI

Inventory shortage manager for retailer order sheets. Upload a photographed
or scanned order sheet (from a phone or a desktop), it finds every row
hand-marked with a cross (X - meaning "not available"), reads the Product
Alias + Quantity for those rows only, auto-corrects rotated/tilted photos
first, and aggregates shortages across every upload into a ready-to-use next
purchase order (Excel export). Every extracted field is editable afterwards,
Excel-style, and you can also type in shortages manually.

## What's new in this version

1. **Everything is editable, spreadsheet-style.**
   - **Orders** page: click any order, its detected rows appear in an
     editable grid - fix a misread alias, quantity, or status right there.
   - **All Records** page (new, `/data`): every row from every upload in one
     editable grid, plus **+ Add Row** to type in a shortage manually (no
     photo needed) and **Delete Selected** to remove bad rows. Edits save
     immediately, cell by cell.
2. **Works on your phone**, including camera capture:
   - The Upload page now has two separate controls: **📷 Take Photo** (opens
     your phone's camera directly) and **🖼️ Upload from Gallery / Files**
     (pick existing photos or PDFs, multiple at once).
   - Nav bar collapses to a hamburger menu on small screens, layout is
     responsive throughout.
   - Add-to-home-screen support (manifest + meta tags) so it behaves like an
     app icon on your phone instead of a browser tab.
3. **Auto-rotation before extraction.** Every image is first sent through a
   quick orientation check - it asks your Groq vision model "how many
   degrees clockwise does this need, plus any small tilt", then physically
   rotates the image with that answer before running the real extraction
   call. If that check ever fails (network hiccup, etc.), it automatically
   falls back to a local, dependency-light OpenCV skew estimate so
   processing never hard-stops just because rotation detection had an issue.

## ⚠️ Important - you chose to deploy on Vercel

Vercel's filesystem is **serverless and ephemeral** - nothing written to disk
survives between requests or deployments, and a plain SQLite file will
silently lose data. To make this deployment-ready, the app now:

- Reads `DATABASE_URL` from your environment. **You must set this to a real
  Postgres connection string** in your Vercel project's Environment
  Variables (Vercel Postgres, [Neon](https://neon.tech), and Supabase all
  have generous free tiers and take under 5 minutes to set up). Without it,
  the app still boots (falls back to a `/tmp` SQLite file) but your data will
  not reliably persist - you'll see a warning in the Vercel function logs if
  this happens.
- Detects it's running on Vercel (`VERCEL=1`, set automatically by Vercel)
  and writes temp files to `/tmp` instead of the deployment bundle, which is
  read-only in production.
- Treats uploaded photos as **transient**: each image is used to extract its
  rows and then discarded - only the extracted data (which is what you
  actually need for the shortage list) is kept, in Postgres. The original
  photo itself is not stored long-term. If you want to keep the original
  photos too, that needs an object store (Vercel Blob / S3) as a follow-up -
  not included in this drop, flag it if you want it added.

### Deploying

1. Push this folder to a GitHub repo.
2. Import it in Vercel ("Add New Project" → your repo). Vercel auto-detects
   the Python/Flask app via `wsgi.py` + `vercel.json`.
3. In Vercel Project Settings → Environment Variables, add:
   - `GROQ_API_KEY` - your Groq key
   - `GROQ_MODEL` - `qwen/qwen3.6-27b` (or whatever you're currently using)
   - `DATABASE_URL` - your Postgres connection string (see above)
4. Deploy. First load will run `init_db()` and create the tables
   automatically against your Postgres database.
5. If you see 504 timeouts on slower extractions: Project Settings →
   Functions → Function Max Duration, raise it (Hobby plan allows a modest
   bump; Pro allows more). `vercel.json` already requests 60s.
6. Open the Vercel URL on your phone - camera capture, editable tables, and
   everything else works the same as local.

### Still fully supported: running locally

```bash
python -m venv venv
source venv/bin/activate      # venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env          # edit .env, add GROQ_API_KEY
python app.py
```
Or just run `run.sh` / `run.bat`, same as before - local runs still default
to a zero-setup local SQLite file, no Postgres required.

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

## Next steps I'd suggest

1. Set up your Postgres database (Neon/Vercel Postgres) before your first
   real deploy so nothing is lost.
2. Run it against a batch of real photographed sheets from your phone and
   check the rotation-correction + confidence thresholds feel right - tune
   thresholds in Settings.
3. Import your product list as the Product Master (Reports page) if you
   have one - meaningfully boosts alias accuracy.
4. Let me know if you want original-photo retention (Vercel Blob) or a
   packaged Windows `.exe` for fully offline/local use as well.
