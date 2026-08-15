from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager

import config
from database.models import Base, AppSetting

engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

# Columns added after the initial release. create_all() only creates missing
# TABLES, not missing columns on tables that already exist, so any existing
# database needs these added by hand the first time it's opened.
_NEW_COLUMNS = {
    "orders": [
        ("order_label", "VARCHAR"),
        ("order_date", "VARCHAR"),
    ],
}


def _run_light_migrations():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all() will have just created it with the new columns already
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_type in columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))


def init_db():
    Base.metadata.create_all(engine)
    _run_light_migrations()
    _seed_default_settings()


def _seed_default_settings():
    defaults = {
        "groq_model": config.GROQ_MODEL_DEFAULT,
        "ocr_confidence_threshold": str(config.DEFAULT_OCR_CONFIDENCE_THRESHOLD),
        "cross_confidence_threshold": str(config.DEFAULT_CROSS_CONFIDENCE_THRESHOLD),
        "alias_regex": config.DEFAULT_ALIAS_REGEX,
        "fuzzy_match_threshold": "85",  # rapidfuzz score 0-100 vs product master
    }
    with session_scope() as s:
        existing = {row.key for row in s.query(AppSetting.key).all()}
        for k, v in defaults.items():
            if k not in existing:
                s.add(AppSetting(key=k, value=v))


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_setting(key, default=None):
    with session_scope() as s:
        row = s.get(AppSetting, key)
        return row.value if row else default


def set_setting(key, value):
    with session_scope() as s:
        row = s.get(AppSetting, key)
        if row:
            row.value = str(value)
        else:
            s.add(AppSetting(key=key, value=str(value)))
