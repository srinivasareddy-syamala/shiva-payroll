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
    emp_type, q = request.args.get("type", ""), request.args.get("q", "").strip()
    eq = Employee.query.filter_by(active=True)
    if emp_type in ("Driver", "Worker"):
        eq = eq.filter_by(emp_type=emp_type)
    if q:
        eq = eq.filter(Employee.name.ilike(f"%{q}%"))
    employees = eq.order_by(Employee.emp_type, Employee.name).all()
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
                           month_label=start.strftime("%B %Y"), emp_type=emp_type, q=q)


def _report_rows(rng, emp_type, q):
    from decimal import Decimal
    from sqlalchemy import func
    emps = Employee.query.filter_by(active=True)
    if emp_type in ("Driver", "Worker"):
        emps = emps.filter_by(emp_type=emp_type)
    if q:
        emps = emps.filter(Employee.name.ilike(f"%{q}%"))
    emps = emps.order_by(Employee.emp_type, Employee.name).all()
    ids = [e.id for e in emps]
    stats = {}
    if ids:
        rows = db.session.query(Attendance.employee_id, Attendance.status, func.count(),
                                func.coalesce(func.sum(Attendance.ot_hours), 0),
                                func.coalesce(func.sum(Attendance.da_amount), 0)) \
            .filter(Attendance.employee_id.in_(ids), Attendance.date.between(rng["start"], rng["end"])) \
            .group_by(Attendance.employee_id, Attendance.status).all()
        for eid, status, cnt, ot, da in rows:
            s = stats.setdefault(eid, {"P": 0, "H": 0, "A": 0, "L": 0, "ot": Decimal(0), "da": Decimal(0)})
            s[status] = cnt
            s["ot"] += Decimal(ot)
            s["da"] += Decimal(da)
    days = (min(rng["end"], today()) - rng["start"]).days + 1
    out = []
    for e in emps:
        s = stats.get(e.id, {"P": 0, "H": 0, "A": 0, "L": 0, "ot": Decimal(0), "da": Decimal(0)})
        paid = sum(Decimal(s[k]) * ATTENDANCE_STATUSES[k][1] for k in ATTENDANCE_STATUSES)
        marked = s["P"] + s["H"] + s["A"] + s["L"]
        out.append({"emp": e, **s, "paid": paid, "worked": s["P"] + s["H"] > 0,
                    "unmarked": max(days - marked, 0)})
    return out, max(days, 0)


@bp.route("/report")
@login_required
def report():
    from ..utils import parse_range
    rng = parse_range(request.args)
    emp_type, q = request.args.get("type", ""), request.args.get("q", "").strip()
    rows, days = _report_rows(rng, emp_type, q)
    show = request.args.get("show", "all")
    if show == "worked":
        rows = [r for r in rows if r["worked"]]
    elif show == "not_worked":
        rows = [r for r in rows if not r["worked"]]
    allrows, _ = _report_rows(rng, emp_type, q)
    summary = {
        "employees": len(allrows),
        "worked": sum(1 for r in allrows if r["worked"]),
        "drivers_worked": sum(1 for r in allrows if r["worked"] and r["emp"].emp_type == "Driver"),
        "workers_worked": sum(1 for r in allrows if r["worked"] and r["emp"].emp_type == "Worker"),
        "paid_days": sum(r["paid"] for r in allrows),
        "da": sum(r["da"] for r in allrows),
        "ot": sum(r["ot"] for r in allrows),
    }
    return render_template("attendance/report.html", rows=rows, rng=rng, days=days, summary=summary,
                           emp_type=emp_type, q=q, show=show)


@bp.route("/report.xlsx")
@login_required
def report_excel():
    from io import BytesIO
    from flask import send_file
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from ..utils import parse_range
    rng = parse_range(request.args)
    rows, days = _report_rows(rng, request.args.get("type", ""), request.args.get("q", "").strip())
    wb = Workbook(); ws = wb.active; ws.title = "Attendance"
    ws.append([f"Attendance {rng['label']}"]); ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Name", "Type", "Present", "Half day", "Absent", "Paid leave", "Paid days", "Not marked", "OT hrs", "DA"])
    for c in ws[2]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1E3A8A")
    for r in rows:
        ws.append([r["emp"].name, r["emp"].emp_type, r["P"], r["H"], r["A"], r["L"], float(r["paid"]),
                   r["unmarked"], float(r["ot"]), float(r["da"])])
    for col, w in zip("ABCDEFGHIJ", [24, 9, 9, 9, 9, 10, 10, 11, 8, 10]):
        ws.column_dimensions[col].width = w
    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"attendance_{rng['start']}_{rng['end']}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
