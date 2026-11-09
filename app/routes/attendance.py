from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import ATTENDANCE_STATUSES, Attendance, Employee
from ..utils import month_bounds, owner_required, parse_month, to_dec, today

bp = Blueprint("attendance", __name__, url_prefix="/attendance")


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return today()


@bp.route("/", methods=["GET", "POST"])
@login_required
def daily():
    day = _parse_date(request.values.get("date"))
    # Supervisors can only work on today's attendance (India time); owners can pick any past date.
    if not current_user.is_owner and day != today():
        if request.values.get("date"):
            flash("Supervisors can mark attendance only for today", "error")
        return redirect(url_for("attendance.daily"))
    if day > today():
        flash("Cannot mark attendance for a future date", "error")
        return redirect(url_for("attendance.daily"))

    employees = Employee.query.filter_by(active=True).order_by(Employee.emp_type, Employee.name).all()
    existing = {a.employee_id: a for a in Attendance.query.filter_by(date=day).all()}

    if request.method == "POST":
        saved = 0
        for emp in employees:
            status = request.form.get(f"status_{emp.id}")
            if status not in ATTENDANCE_STATUSES:
                continue
            rec = existing.get(emp.id) or Attendance(employee_id=emp.id, date=day)
            rec.status = status
            rec.ot_hours = to_dec(request.form.get(f"ot_{emp.id}"))
            rec.da_amount = max(to_dec(request.form.get(f"da_{emp.id}")), 0)
            rec.remarks = request.form.get(f"remarks_{emp.id}", "").strip() or None
            rec.marked_by = current_user.id
            rec.marked_at = datetime.utcnow()
            db.session.add(rec)
            saved += 1
        db.session.commit()
        flash(f"Attendance saved for {saved} employees on {day.strftime('%d %b %Y')}", "success")
        return redirect(url_for("attendance.daily", date=day.isoformat()))

    return render_template("attendance/daily.html", day=day, employees=employees,
                           existing=existing, statuses=ATTENDANCE_STATUSES,
                           prev_day=day - timedelta(days=1),
                           next_day=day + timedelta(days=1) if day < today() else None)


@bp.route("/month")
@login_required
def monthly():
    year, month = parse_month(request.args.get("month"))
    start, end, days = month_bounds(year, month)
    employees = Employee.query.filter_by(active=True).order_by(Employee.emp_type, Employee.name).all()
    grid, da_days, da_total = {}, set(), {}
    for a in Attendance.query.filter(Attendance.date.between(start, end)).all():
        grid[(a.employee_id, a.date.day)] = a.status
        if a.da_amount and a.da_amount > 0:
            da_days.add((a.employee_id, a.date.day))
            da_total[a.employee_id] = da_total.get(a.employee_id, 0) + a.da_amount
    totals = {}
    for emp in employees:
        paid = sum(ATTENDANCE_STATUSES[grid[(emp.id, d)]][1]
                   for d in range(1, days + 1) if (emp.id, d) in grid)
        totals[emp.id] = paid
    return render_template("attendance/monthly.html", employees=employees, grid=grid,
                           days=range(1, days + 1), totals=totals, da_days=da_days, da_total=da_total, year=year, month=month,
                           month_value=f"{year:04d}-{month:02d}",
                           month_label=start.strftime("%B %Y"))
