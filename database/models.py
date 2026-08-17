from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class ImageRecord(Base):
    """Every uploaded file (image or a single PDF page) becomes one ImageRecord."""
    __tablename__ = "images"

    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    # Path to the image actually shown for verification (enhanced/deskewed
    # version - closest to what the model saw). Falls back to filepath if
    # processing failed before this was set.
    display_path = Column(String, nullable=True)
    retailer_name = Column(String, default="Unknown Retailer")
    upload_date = Column(DateTime, default=datetime.utcnow)
    processing_status = Column(String, default="pending")  # pending/processing/done/failed
    error_message = Column(Text, nullable=True)

    # Who uploaded this (free-text name picked from the navbar dropdown -
    # no password, no accounts, just attribution for a small shared team).
    uploaded_by = Column(String, nullable=True, default="")

    # Duplicate detection - see services/dedup.py.
    content_hash = Column(String, nullable=True, index=True)  # SHA-256 of raw file bytes
    phash = Column(String, nullable=True)  # perceptual hash of the enhanced image

    # Rough Groq token usage for this image's extraction call(s) - a cost/
    # usage trend indicator, not a live per-minute quota gauge.
    tokens_used = Column(Integer, nullable=True, default=0)

    order = relationship("OrderRecord", back_populates="image", uselist=False)
    missing_products = relationship("MissingProduct", back_populates="image")


class OrderRecord(Base):
    """One order = one processed upload (image or pdf page)."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False)
    retailer_name = Column(String, default="Unknown Retailer")
    created_at = Column(DateTime, default=datetime.now)

    # order_label: the "Order ID" shown/edited in the data table. Shared by
    # every row extracted from the same sheet/image. Defaults to the numeric
    # order id for image-extracted orders; left blank ("") for manual entries
    # so the user can type their own.
    order_label = Column(String, nullable=True, default="")
    # order_date: printed exactly as it appears on the sheet (top-right corner),
    # e.g. "15/08/2026". Blank for manual entries.
    order_date = Column(String, nullable=True, default="")

    image = relationship("ImageRecord", back_populates="order")
    missing_products = relationship("MissingProduct", back_populates="order")


class MissingProduct(Base):
    """A single X-marked row extracted from an order sheet."""
    __tablename__ = "missing_products"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False)

    product_alias = Column(String, nullable=False, index=True)
    required_quantity = Column(Float, default=0)
    row_sr_no = Column(String, nullable=True)
    raw_row_text = Column(Text, nullable=True)

    ocr_confidence = Column(Float, default=0.0)
    cross_confidence = Column(Float, default=0.0)

    # pending = needs manual review, accepted = counted in aggregation, rejected = ignored
    status = Column(String, default="pending")

    created_at = Column(DateTime, default=datetime.now)

    order = relationship("OrderRecord", back_populates="missing_products")
    image = relationship("ImageRecord", back_populates="missing_products")


class ProductMaster(Base):
    """Optional master list to validate OCR'd aliases against."""
    __tablename__ = "product_master"

    product_alias = Column(String, primary_key=True)
    product_name = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    category = Column(String, nullable=True)
    mrp = Column(Float, nullable=True)
    current_stock = Column(Float, nullable=True)
    # Minimum order quantity - if set, Reports export rounds a purchase
    # order up to this instead of the raw shortfall.
    moq = Column(Float, nullable=True)


class AppUser(Base):
    """Lightweight, password-free user list - a name picked from a navbar
    dropdown so uploads/edits can be attributed, plus an admin flag that
    gates the Insights page. No login, no security boundary - by design,
    for a small trusted team."""
    __tablename__ = "app_users"

    name = Column(String, primary_key=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)


class AppSetting(Base):
    """Simple local key/value settings store (thresholds, model name, etc)."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)
