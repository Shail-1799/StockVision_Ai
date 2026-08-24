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
# Small-angle skew is straightened locally via OpenCV (services/rotation.py) -
# no API call. Gross 90/180/270 rotation is reported as an extra field on
# the same Groq extraction call rather than a separate request. Set to
# "false" to skip local deskewing entirely (rarely needed).
AUTO_ROTATE_ENABLED = os.environ.get("AUTO_ROTATE_ENABLED", "true").lower() != "false"

# --- Multi-user note ---
# With several people uploading at once, SQLite's single-writer file lock
# can serialize/stall concurrent uploads. For ~10 concurrent users, set a
# real DATABASE_URL (Postgres) as above - the app already supports it,
# nothing else to change.

# --- Auth / sessions ---
# Signs the login session cookie. MUST be set to a fixed value via the
# SECRET_KEY env var in production (Render Settings -> Environment) - if
# left unset, a random key is generated at process start, which works but
# silently logs everyone out on every deploy/restart since old cookies were
# signed with a key that no longer exists.
import secrets as _secrets
_env_secret = os.environ.get("SECRET_KEY", "").strip()
if _env_secret:
    SECRET_KEY = _env_secret
else:
    SECRET_KEY = _secrets.token_hex(32)
    if not IS_SERVERLESS:
        import logging
        logging.getLogger(__name__).warning(
            "SECRET_KEY not set - using a random key for this process. Set a "
            "fixed SECRET_KEY env var in production or everyone gets logged "
            "out on every restart/deploy."
        )

SESSION_LIFETIME_DAYS = 7
# Cookies only over HTTPS in production; allow plain http for local dev.
# Render sets RENDER=true on its own, so this needs no manual configuration.
SESSION_COOKIE_SECURE = bool(os.environ.get("RENDER") or IS_SERVERLESS)
