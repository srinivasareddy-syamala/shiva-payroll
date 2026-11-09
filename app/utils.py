import calendar
import os
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from flask import abort
from flask_login import current_user


def _tz():
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))
    except Exception:
        from datetime import timedelta
        return timezone(timedelta(hours=5, minutes=30))


def today():
    """Today's date in India time, whatever timezone the server runs in."""
    return datetime.now(_tz()).date()


def now_local():
    return datetime.now(_tz())


def localtime(dt, fmt="%d %b, %I:%M %p"):
    """Format a UTC timestamp stored in the DB as India time."""
    if not dt:
        return ""
    return dt.replace(tzinfo=timezone.utc).astimezone(_tz()).strftime(fmt).replace(" 0", " ").lstrip("0")


def can_change(d):
    """Owners can change any date; supervisors only today's entries (India time)."""
    if current_user.is_authenticated and current_user.is_owner:
        return True
    if isinstance(d, datetime):
        d = d.date()
    return d == today()


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
        t = today()
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
    name = f"{prefix}_{today():%Y%m%d}_{uuid.uuid4().hex[:10]}"
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


RANGE_PRESETS = [("today", "Today"), ("this_week", "This week"), ("last_week", "Last week"),
                 ("this_month", "This month"), ("last_month", "Last month"), ("custom", "Custom")]


def parse_range(args, default="this_week"):
    """Date range from ?range=...&from=YYYY-MM-DD&to=YYYY-MM-DD. Weeks run Monday–Sunday.
    Returns dict(start, end, key, label)."""
    from datetime import timedelta
    t = today()
    key = args.get("range") or default
    start = end = t
    if key == "today":
        pass
    elif key == "this_week":
        start, end = t - timedelta(days=t.weekday()), t
    elif key == "last_week":
        end = t - timedelta(days=t.weekday() + 1)
        start = end - timedelta(days=6)
    elif key == "this_month":
        start, end = t.replace(day=1), t
    elif key == "last_month":
        end = t.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:
        key = "custom"
        try:
            start = datetime.strptime(args.get("from", ""), "%Y-%m-%d").date()
        except ValueError:
            start = t - timedelta(days=t.weekday())
        try:
            end = datetime.strptime(args.get("to", ""), "%Y-%m-%d").date()
        except ValueError:
            end = t
        if end < start:
            start, end = end, start
        if (end - start).days > 400:
            start = end - timedelta(days=400)
    label = start.strftime("%d %b %Y") if start == end else f"{start:%d %b} – {end:%d %b %Y}"
    return {"start": start, "end": end, "key": key, "label": label}
