import calendar
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from flask import abort
from flask_login import current_user


def owner_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_owner:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def to_dec(value, default="0"):
    try:
        v = str(value).strip().replace(",", "")
        return Decimal(v if v else default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def money(d):
    return Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def inr(value):
    """Indian number format: 1,23,456.00"""
    if value is None:
        return "₹0"
    d = money(value)
    neg = d < 0
    s = f"{abs(d):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = f"₹{whole}" + (f".{frac}" if frac != "00" else "")
    return f"-{out}" if neg else out


def days(value):
    """26.0 -> '26', 25.5 -> '25.5'"""
    d = Decimal(value or 0).normalize()
    return f"{d:f}"


def month_bounds(year, month):
    days = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, days), days


def parse_month(value):
    """'2026-11' -> (2026, 11); defaults to current month."""
    try:
        y, m = value.split("-")
        return int(y), int(m)
    except (AttributeError, ValueError):
        t = date.today()
        return t.year, t.month


ALLOWED_UPLOADS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic"}


def save_upload(file_storage, prefix="slip"):
    """Save an uploaded bill/slip. Photos are shrunk to max 1600px JPEG. Returns stored filename or None."""
    import os
    import uuid
    from flask import current_app

    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_UPLOADS:
        raise ValueError("Only photos (JPG/PNG) or PDF files are allowed")
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    name = f"{prefix}_{date.today():%Y%m%d}_{uuid.uuid4().hex[:10]}"
    if ext == ".pdf":
        fname = name + ".pdf"
        file_storage.save(os.path.join(folder, fname))
        return fname
    try:
        from PIL import Image, ImageOps
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1600, 1600))
        fname = name + ".jpg"
        img.save(os.path.join(folder, fname), "JPEG", quality=82, optimize=True)
        return fname
    except Exception:
        file_storage.stream.seek(0)
        fname = name + ext
        file_storage.save(os.path.join(folder, fname))
        return fname
