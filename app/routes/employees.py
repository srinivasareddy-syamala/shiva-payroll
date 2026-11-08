from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import ATTENDANCE_STATUSES, Advance, Attendance, Employee, SalaryPayment
from ..payroll import attendance_summary
from ..utils import month_bounds, owner_required, parse_month, to_dec

bp = Blueprint("employees", __name__, url_prefix="/employees")


def _fill(emp, f):
    emp.name = f.get("name", "").strip()
    emp.phone = f.get("phone", "").strip()
    emp.whatsapp = f.get("whatsapp", "").strip() or None
    emp.emp_type = f.get("emp_type", "Worker")
    emp.pay_type = f.get("pay_type", "Monthly")
    emp.rate = to_dec(f.get("rate"))
    emp.ot_rate = to_dec(f.get("ot_rate"))
    emp.vehicle_no = f.get("vehicle_no", "").strip() or None
    jd = f.get("joining_date")
    emp.joining_date = datetime.strptime(jd, "%Y-%m-%d").date() if jd else date.today()
    emp.active = f.get("active") == "on"
    emp.notes = f.get("notes", "").strip() or None


@bp.route("/")
@login_required
@owner_required
def index():
    show = request.args.get("show", "active")
    q = Employee.query
    if show == "active":
        q = q.filter_by(active=True)
    elif show == "inactive":
        q = q.filter_by(active=False)
    search = request.args.get("q", "").strip()
    if search:
        q = q.filter(Employee.name.ilike(f"%{search}%"))
    emps = q.order_by(Employee.emp_type, Employee.name).all()
    return render_template("employees/index.html", employees=emps, show=show, search=search)


@bp.route("/new", methods=["GET", "POST"])
@login_required
@owner_required
def new():
    emp = Employee(active=True, joining_date=date.today())
    if request.method == "POST":
        _fill(emp, request.form)
        if not emp.name:
            flash("Name is required", "error")
        else:
            db.session.add(emp)
            db.session.commit()
            flash(f"{emp.name} added", "success")
            return redirect(url_for("employees.index"))
    return render_template("employees/form.html", emp=emp)


@bp.route("/<int:emp_id>/edit", methods=["GET", "POST"])
@login_required
@owner_required
def edit(emp_id):
    emp = db.get_or_404(Employee, emp_id)
    if request.method == "POST":
        _fill(emp, request.form)
        if not emp.name:
            flash("Name is required", "error")
        else:
            db.session.commit()
            flash("Saved", "success")
            return redirect(url_for("employees.ledger", emp_id=emp.id))
    return render_template("employees/form.html", emp=emp)


@bp.route("/<int:emp_id>")
@login_required
@owner_required
def ledger(emp_id):
    emp = db.get_or_404(Employee, emp_id)
    year, month = parse_month(request.args.get("month"))
    start, end, ndays = month_bounds(year, month)
    summary = attendance_summary(emp, year, month)
    records = {a.date: a for a in Attendance.query.filter(
        Attendance.employee_id == emp.id, Attendance.date.between(start, end)).all()}
    today = date.today()
    day_rows = []
    for i in range(ndays):
        d = start + timedelta(days=i)
        if d > today:
            break
        day_rows.append((d, records.get(d)))
    advances = emp.advances.order_by(Advance.date.desc()).all()
    payments = emp.payments.order_by(SalaryPayment.year.desc(), SalaryPayment.month.desc()).all()
    month_payment = next((p for p in payments if p.year == year and p.month == month), None)
    return render_template("employees/ledger.html", emp=emp, summary=summary,
                           day_rows=day_rows, statuses=ATTENDANCE_STATUSES,
                           advances=advances, payments=payments, month_payment=month_payment,
                           outstanding=emp.advance_outstanding(),
                           month_value=f"{year:04d}-{month:02d}", month_label=start.strftime("%B %Y"))


@bp.route("/<int:emp_id>/day/<day>", methods=["POST"])
@login_required
@owner_required
def day_update(emp_id, day):
    """Admin edit / delete of one day's ledger entry (attendance, OT, DA, remarks)."""
    emp = db.get_or_404(Employee, emp_id)
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date", "error")
        return redirect(url_for("employees.ledger", emp_id=emp.id))
    rec = Attendance.query.filter_by(employee_id=emp.id, date=d).first()
    month_value = d.strftime("%Y-%m")

    if request.form.get("action") == "delete":
        if rec:
            db.session.delete(rec)
            db.session.commit()
            flash(f"Deleted entry for {d.strftime('%d %b %Y')}", "success")
    else:
        status = request.form.get("status")
        if status not in ATTENDANCE_STATUSES:
            flash("Choose P / H / A / L", "error")
            return redirect(url_for("employees.ledger", emp_id=emp.id, month=month_value) + f"#d{day}")
        rec = rec or Attendance(employee_id=emp.id, date=d)
        rec.status = status
        rec.ot_hours = max(to_dec(request.form.get("ot")), 0)
        rec.da_amount = max(to_dec(request.form.get("da")), 0)
        rec.remarks = request.form.get("remarks", "").strip() or None
        rec.marked_by = current_user.id
        db.session.add(rec)
        db.session.commit()
        flash(f"Saved {d.strftime('%d %b %Y')}", "success")

    if SalaryPayment.query.filter_by(employee_id=emp.id, year=d.year, month=d.month).first():
        flash("Salary for this month was already saved. Open Salary and press Save again to update the slip.", "error")
    return redirect(url_for("employees.ledger", emp_id=emp.id, month=month_value) + f"#d{day}")
