"""
StockVision AI - central configuration.
Reads from .env if present, falls back to sane local-first defaults.
Nothing here requires internet access except the Groq API call itself.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- Serverless detection ---
# Vercel (and most serverless hosts) set VERCEL=1 and only allow writes under
# /tmp - everything else in the deployment bundle is read-only. When running
# locally / on your own machine, we use folders next to app.py as before.
IS_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("SERVERLESS"))

if IS_SERVERLESS:
    _writable_root = Path("/tmp/stockvision")
else:
    _writable_root = BASE_DIR

UPLOADS_DIR = _writable_root / "uploads"
PROCESSED_DIR = _writable_root / "processed"
EXPORTS_DIR = _writable_root / "exports"
LOGS_DIR = _writable_root / "logs"
DATABASE_DIR = _writable_root / "database"

for d in (UPLOADS_DIR, PROCESSED_DIR, EXPORTS_DIR, LOGS_DIR, DATABASE_DIR):
    d.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATABASE_DIR / "stockvision.db"

# --- Database URL ---
# Local dev: plain SQLite file, zero setup.
# Deployed (Vercel etc): set DATABASE_URL to a real Postgres connection
# string (Vercel Postgres / Neon / Supabase all work) as a project env var -
# a serverless filesystem can't be trusted to keep a SQLite file around
# between requests, let alone between deployments.
_env_db_url = os.environ.get("DATABASE_URL", "").strip()
if _env_db_url:
    # Vercel/Neon sometimes hand out "postgres://" - SQLAlchemy needs "postgresql://"
    DATABASE_URL = _env_db_url.replace("postgres://", "postgresql://", 1)
elif IS_SERVERLESS:
    # No DATABASE_URL set on a serverless deploy - fall back to a /tmp SQLite
    # file so the app still boots, but data will NOT persist reliably.
    # Add a Postgres DATABASE_URL in your Vercel project settings to fix this.
    DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
else:
    DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

USING_SQLITE_ON_SERVERLESS = IS_SERVERLESS and DATABASE_URL.startswith("sqlite")

# --- Groq Vision model ---
# You told us you have a working vision model on Groq: qwen/qwen3.6-27b.
# We default to that, but it's fully overridable from the Settings page
# or the .env file, in case the exact model slug changes on Groq's side.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL_DEFAULT = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")

# --- Detection / validation defaults (overridable in Settings page, stored in DB) ---
DEFAULT_OCR_CONFIDENCE_THRESHOLD = 0.75
DEFAULT_CROSS_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_ALIAS_REGEX = r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$"

APP_TITLE = "StockVision AI"
APP_PORT = int(os.environ.get("PORT", 8050))

# --- Image rotation correction ---
# 0/90/180/270 gross-rotation + fine skew is detected with a cheap Groq vision
# call before the main extraction call. If that fails (no key yet, network
# hiccup, etc) we fall back to a local OpenCV-only fine-skew estimate.
AUTO_ROTATE_ENABLED = os.environ.get("AUTO_ROTATE_ENABLED", "true").lower() != "false"
