import os
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   send_file, send_from_directory, url_for)
from flask_login import current_user, login_required
from sqlalchemy import func

from .. import db
from ..models import EXPENSE_CATEGORIES, Employee, Vehicle, VehicleExpense
from ..utils import month_bounds, owner_required, parse_month, save_upload, to_dec, today

bp = Blueprint("vehicles", __name__, url_prefix="/vehicles")

VEHICLE_TYPES = ["Truck", "Mini truck", "Pickup", "Van", "Tractor", "Other"]


def _int(v):
    try:
        return int(str(v).strip()) if str(v).strip() else None
    except ValueError:
        return None


def _month_ctx():
    year, month = parse_month(request.args.get("month"))
    start, end, _ = month_bounds(year, month)
    return year, month, start, end, f"{year:04d}-{month:02d}", start.strftime("%B %Y")


def pending_count():
    return VehicleExpense.query.filter_by(status="Pending").count()


# ---------------- Vehicles ----------------

@bp.route("/")
@login_required
def index():
    year, month, start, end, month_value, month_label = _month_ctx()
    vehicles = Vehicle.query.order_by(Vehicle.active.desc(), Vehicle.number).all()
    totals = {}
    if current_user.is_owner:
        rows = db.session.query(VehicleExpense.vehicle_id, VehicleExpense.category,
                                func.sum(VehicleExpense.amount), func.coalesce(func.sum(VehicleExpense.litres), 0)) \
            .filter(VehicleExpense.status == "Approved", VehicleExpense.date.between(start, end)) \
            .group_by(VehicleExpense.vehicle_id, VehicleExpense.category).all()
        for vid, cat, amt, lit in rows:
            t = totals.setdefault(vid, {"total": Decimal(0), "litres": Decimal(0)})
            t[cat] = amt
            t["total"] += amt
            if cat == "Diesel":
                t["litres"] = lit
    grand = {c: sum((t.get(c, 0) for t in totals.values()), Decimal(0)) for c in EXPENSE_CATEGORIES}
    grand["total"] = sum(grand.values(), Decimal(0))
    return render_template("vehicles/index.html", vehicles=vehicles, totals=totals, grand=grand,
                           categories=EXPENSE_CATEGORIES, month_value=month_value, month_label=month_label,
                           pending=pending_count() if current_user.is_owner else 0)


def _fill_vehicle(v, f):
    v.number = f.get("number", "").strip().upper().replace(" ", "")
    v.vehicle_type = f.get("vehicle_type", "Truck")
    v.model = f.get("model", "").strip() or None
    v.capacity = f.get("capacity", "").strip() or None
    v.driver_id = _int(f.get("driver_id"))
    v.active = f.get("active") == "on"
    v.notes = f.get("notes", "").strip() or None


@bp.route("/new", methods=["GET", "POST"])
@login_required
@owner_required
def new():
    v = Vehicle(active=True)
    if request.method == "POST":
        _fill_vehicle(v, request.form)
        if not v.number:
            flash("Vehicle number is required", "error")
        elif Vehicle.query.filter_by(number=v.number).first():
            flash("This vehicle number already exists", "error")
        else:
            db.session.add(v)
            db.session.commit()
            flash(f"Vehicle {v.number} added", "success")
            return redirect(url_for("vehicles.index"))
    return render_template("vehicles/form.html", v=v, types=VEHICLE_TYPES, drivers=_drivers())


@bp.route("/<int:vid>/edit", methods=["GET", "POST"])
@login_required
@owner_required
def edit(vid):
    v = db.get_or_404(Vehicle, vid)
    if request.method == "POST":
        _fill_vehicle(v, request.form)
        dup = Vehicle.query.filter(Vehicle.number == v.number, Vehicle.id != v.id).first()
        if not v.number or dup:
            flash("Vehicle number is required and must be unique", "error")
        else:
            db.session.commit()
            flash("Vehicle saved", "success")
            return redirect(url_for("vehicles.detail", vid=v.id))
    return render_template("vehicles/form.html", v=v, types=VEHICLE_TYPES, drivers=_drivers())


@bp.route("/<int:vid>/delete", methods=["POST"])
@login_required
@owner_required
def delete(vid):
    v = db.get_or_404(Vehicle, vid)
    if v.expenses.count():
        v.active = False
        db.session.commit()
        flash(f"{v.number} has expenses, so it was marked inactive instead of deleted", "error")
    else:
        db.session.delete(v)
        db.session.commit()
        flash("Vehicle deleted", "success")
    return redirect(url_for("vehicles.index"))


def _drivers():
    return Employee.query.filter_by(active=True).order_by(Employee.emp_type, Employee.name).all()


@bp.route("/<int:vid>")
@login_required
@owner_required
def detail(vid):
    v = db.get_or_404(Vehicle, vid)
    year, month, start, end, month_value, month_label = _month_ctx()
    expenses = v.expenses.filter(VehicleExpense.date.between(start, end)) \
        .order_by(VehicleExpense.date.desc(), VehicleExpense.id.desc()).all()
    approved = [e for e in expenses if e.status == "Approved"]
    by_cat = {c: sum((e.amount for e in approved if e.category == c), Decimal(0)) for c in EXPENSE_CATEGORIES}
    diesel = [e for e in approved if e.category == "Diesel"]
    litres = sum((e.litres or 0 for e in diesel), Decimal(0))
    # mileage from odometer readings on diesel fills this month
    odos = sorted(e.odometer for e in diesel if e.odometer)
    km = (odos[-1] - odos[0]) if len(odos) >= 2 else None
    # litres used between first and last reading = all fills except the last one
    if km:
        fills = sorted((e for e in diesel if e.odometer), key=lambda e: e.odometer)
        used = sum((e.litres or 0 for e in fills[:-1]), Decimal(0))
        kmpl = (Decimal(km) / used).quantize(Decimal("0.01")) if used else None
    else:
        kmpl = None
    birds = sum((e.birds or 0 for e in approved if e.category == "Loading"))
    loading = by_cat.get("Loading", 0)
    return render_template("vehicles/detail.html", v=v, expenses=expenses, by_cat=by_cat,
                           total=sum(by_cat.values(), Decimal(0)), litres=litres, km=km, kmpl=kmpl,
                           birds=birds, per_bird=(loading / birds).quantize(Decimal("0.01")) if birds else None,
                           categories=EXPENSE_CATEGORIES, month_value=month_value, month_label=month_label)


# ---------------- Expenses ----------------

def _remove_file(name):
    if name:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
        except OSError:
            pass


def _can_edit(e):
    return current_user.is_owner or (e.submitted_by == current_user.id and e.status != "Approved")


def _fill_expense(e, f, files):
    e.vehicle_id = _int(f.get("vehicle_id"))
    e.category = f.get("category") if f.get("category") in EXPENSE_CATEGORIES else "Other"
    if current_user.is_owner:
        d = f.get("date")
        e.date = datetime.strptime(d, "%Y-%m-%d").date() if d else today()
    elif not e.id:
        e.date = today()  # supervisors: always today's date (India time); time is kept in created_at
    e.amount = to_dec(f.get("amount"))
    e.litres = to_dec(f.get("litres")) if e.category == "Diesel" and f.get("litres") else None
    e.odometer = _int(f.get("odometer"))
    e.birds = _int(f.get("birds")) if e.category == "Loading" else None
    e.labourers = _int(f.get("labourers")) if e.category == "Loading" else None
    e.bill_no = f.get("bill_no", "").strip() or None
    e.vendor = f.get("vendor", "").strip() or None
    e.description = f.get("description", "").strip() or None
    e.payment_mode = f.get("payment_mode", "Cash")
    e.driver_id = _int(f.get("driver_id"))
    up = next((files.get(k) for k in ("slip_camera", "slip_file", "slip")
               if files.get(k) and files.get(k).filename), None)
    if up:
        old = e.slip_file
        e.slip_file = save_upload(up, prefix=e.category.lower())
        if old and old != e.slip_file:
            _remove_file(old)


def _validate(e):
    if not e.vehicle_id or not db.session.get(Vehicle, e.vehicle_id):
        return "Choose a vehicle"
    if e.amount <= 0:
        return "Amount must be greater than 0"
    if e.date > today():
        return "Date cannot be in the future"
    if e.category == "Diesel" and not e.slip_file:
        return "Diesel entries need a photo of the bill slip"
    return None


@bp.route("/expenses/new", methods=["GET", "POST"])
@login_required
def expense_new():
    e = VehicleExpense(date=today(), category=request.args.get("category", "Diesel"),
                       vehicle_id=_int(request.args.get("vehicle")))
    if request.method == "POST":
        try:
            _fill_expense(e, request.form, request.files)
            err = _validate(e)
        except ValueError as ex:
            err = str(ex)
        if err:
            flash(err, "error")
        else:
            e.submitted_by = current_user.id
            # Owner's own entries are approved straight away, except diesel when "send for approval" is ticked.
            # Supervisor entries always wait for owner approval.
            if current_user.is_owner and request.form.get("needs_approval") != "on":
                e.status, e.reviewed_by, e.reviewed_at = "Approved", current_user.id, datetime.utcnow()
            else:
                e.status = "Pending"
            db.session.add(e)
            db.session.commit()
            flash(f"{e.category} expense saved" + (" — waiting for owner approval" if e.status == "Pending" else ""),
                  "success")
            if request.form.get("again") == "1":
                return redirect(url_for("vehicles.expense_new", category=e.category, vehicle=e.vehicle_id))
            return redirect(url_for("vehicles.expenses"))
    return render_template("vehicles/expense_form.html", e=e, vehicles=_active_vehicles(e),
                           drivers=_drivers(), categories=EXPENSE_CATEGORIES)


def _active_vehicles(e=None):
    q = Vehicle.query.filter((Vehicle.active.is_(True)) | (Vehicle.id == (e.vehicle_id if e else None)))
    return q.order_by(Vehicle.number).all()


@bp.route("/expenses/<int:eid>/edit", methods=["GET", "POST"])
@login_required
def expense_edit(eid):
    e = db.get_or_404(VehicleExpense, eid)
    if not _can_edit(e):
        abort(403)
    if request.method == "POST":
        try:
            _fill_expense(e, request.form, request.files)
            err = _validate(e)
        except ValueError as ex:
            err = str(ex)
        if err:
            flash(err, "error")
            db.session.rollback()
        else:
            if not current_user.is_owner and e.status == "Rejected":
                e.status = "Pending"  # resubmitted after correction
            db.session.commit()
            flash("Expense updated", "success")
            return redirect(request.form.get("next") or url_for("vehicles.expenses"))
    return render_template("vehicles/expense_form.html", e=e, vehicles=_active_vehicles(e),
                           drivers=_drivers(), categories=EXPENSE_CATEGORIES, next=request.args.get("next", ""))


@bp.route("/expenses/<int:eid>/delete", methods=["POST"])
@login_required
def expense_delete(eid):
    e = db.get_or_404(VehicleExpense, eid)
    if not (current_user.is_owner or (e.submitted_by == current_user.id and e.status == "Pending")):
        abort(403)
    _remove_file(e.slip_file)
    db.session.delete(e)
    db.session.commit()
    flash("Expense deleted", "success")
    return redirect(request.referrer or url_for("vehicles.expenses"))


def _expense_query():
    year, month, start, end, month_value, month_label = _month_ctx()
    q = VehicleExpense.query.filter(VehicleExpense.date.between(start, end))
    vid, cat, status = _int(request.args.get("vehicle")), request.args.get("category"), request.args.get("status")
    if vid:
        q = q.filter_by(vehicle_id=vid)
    if cat in EXPENSE_CATEGORIES:
        q = q.filter_by(category=cat)
    if status in ("Pending", "Approved", "Rejected"):
        q = q.filter_by(status=status)
    if not current_user.is_owner:
        q = q.filter_by(submitted_by=current_user.id)
    return q.order_by(VehicleExpense.date.desc(), VehicleExpense.id.desc()), month_value, month_label


@bp.route("/expenses")
@login_required
def expenses():
    q, month_value, month_label = _expense_query()
    items = q.all()
    total = sum((e.amount for e in items if e.status == "Approved"), Decimal(0))
    return render_template("vehicles/expenses.html", items=items, total=total,
                           vehicles=Vehicle.query.order_by(Vehicle.number).all(), categories=EXPENSE_CATEGORIES,
                           month_value=month_value, month_label=month_label, args=request.args)


@bp.route("/expenses.xlsx")
@login_required
@owner_required
def expenses_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    q, month_value, _ = _expense_query()
    wb = Workbook()
    ws = wb.active
    ws.title = month_value
    ws.append(["Date", "Vehicle", "Category", "Amount", "Litres", "Rate/L", "Odometer", "Birds", "Labourers",
               "Bill no", "Vendor / place", "Description", "Mode", "Driver", "Status", "Submitted by", "Review note"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1E3A8A")
    rows = q.all()
    for e in rows:
        ws.append([e.date.strftime("%d-%m-%Y"), e.vehicle.number, e.category, float(e.amount),
                   float(e.litres) if e.litres else None, float(e.rate_per_litre) if e.rate_per_litre else None,
                   e.odometer, e.birds, e.labourers, e.bill_no, e.vendor, e.description, e.payment_mode,
                   e.driver.name if e.driver else "", e.status, e.submitter.username if e.submitter else "",
                   e.review_note])
    n = len(rows) + 1
    ws.append(["TOTAL (all rows)", "", "", f"=SUM(D2:D{n})"])
    for c in ws[n + 1]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJKLMNOPQ", [11, 12, 10, 11, 8, 8, 10, 8, 9, 10, 18, 28, 8, 14, 10, 12, 18]):
        ws.column_dimensions[col].width = w
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"vehicle_expenses_{month_value}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------- Approvals ----------------

@bp.route("/approvals", methods=["GET", "POST"])
@login_required
@owner_required
def approvals():
    if request.method == "POST":
        ids = [_int(i) for i in request.form.getlist("ids")] or [_int(request.form.get("id"))]
        action = request.form.get("action")
        note = request.form.get("note", "").strip() or None
        if action not in ("approve", "reject"):
            abort(400)
        if action == "reject" and not note:
            flash("Please write a reason when rejecting", "error")
            return redirect(url_for("vehicles.approvals"))
        n = 0
        for i in ids:
            e = db.session.get(VehicleExpense, i) if i else None
            if e and e.status == "Pending":
                e.status = "Approved" if action == "approve" else "Rejected"
                e.reviewed_by, e.reviewed_at, e.review_note = current_user.id, datetime.utcnow(), note
                n += 1
        db.session.commit()
        flash(f"{n} expense(s) {'approved' if action == 'approve' else 'rejected'}", "success" if n else "error")
        return redirect(url_for("vehicles.approvals"))
    items = VehicleExpense.query.filter_by(status="Pending") \
        .order_by(VehicleExpense.date, VehicleExpense.id).all()
    recent = VehicleExpense.query.filter(VehicleExpense.status != "Pending", VehicleExpense.reviewed_at.isnot(None)) \
        .order_by(VehicleExpense.reviewed_at.desc()).limit(10).all()
    return render_template("vehicles/approvals.html", items=items, recent=recent)


@bp.route("/slip/<int:eid>")
@login_required
def slip(eid):
    e = db.get_or_404(VehicleExpense, eid)
    if not (current_user.is_owner or e.submitted_by == current_user.id) or not e.slip_file:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], e.slip_file)
