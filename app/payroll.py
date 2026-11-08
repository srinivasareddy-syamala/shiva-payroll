"""Salary calculation — one place for all money logic."""
from decimal import Decimal

from sqlalchemy import func

from . import db
from .models import ATTENDANCE_STATUSES, Attendance, SalaryPayment
from .utils import money, month_bounds


def attendance_summary(employee, year, month):
    start, end, days = month_bounds(year, month)
    rows = db.session.query(Attendance.status, func.count(),
                            func.coalesce(func.sum(Attendance.ot_hours), 0),
                            func.coalesce(func.sum(Attendance.da_amount), 0)) \
        .filter(Attendance.employee_id == employee.id, Attendance.date.between(start, end)) \
        .group_by(Attendance.status).all()
    counts = {k: 0 for k in ATTENDANCE_STATUSES}
    ot = Decimal("0")
    da = Decimal("0")
    for status, cnt, ot_sum, da_sum in rows:
        counts[status] = cnt
        ot += Decimal(ot_sum)
        da += Decimal(da_sum)
    paid_days = sum(Decimal(counts[k]) * ATTENDANCE_STATUSES[k][1] for k in counts)
    return {
        "counts": counts,
        "paid_days": paid_days,
        "ot_hours": ot,
        "da_amount": money(da),
        "da_days": db.session.query(func.count()).filter(
            Attendance.employee_id == employee.id, Attendance.date.between(start, end),
            Attendance.da_amount > 0).scalar(),
        "days_in_month": days,
        "marked_days": sum(counts.values()),
    }


def da_entries(employee, year, month):
    """Day-wise DA list for the slip / WhatsApp message."""
    start, end, _ = month_bounds(year, month)
    return Attendance.query.filter(Attendance.employee_id == employee.id,
                                   Attendance.date.between(start, end),
                                   Attendance.da_amount > 0).order_by(Attendance.date).all()


def calculate(employee, year, month):
    """Suggested salary for the month (not saved)."""
    s = attendance_summary(employee, year, month)
    rate = Decimal(employee.rate)
    if employee.pay_type == "Monthly":
        earned = rate / s["days_in_month"] * s["paid_days"]
    else:
        earned = rate * s["paid_days"]
    ot_amount = Decimal(employee.ot_rate) * s["ot_hours"]
    earned, ot_amount = money(earned), money(ot_amount)

    existing = SalaryPayment.query.filter_by(employee_id=employee.id, year=year, month=month).first()
    outstanding = employee.advance_due_for_month(year, month)
    gross = earned + ot_amount + s["da_amount"]
    suggested_adv = money(max(Decimal("0"), min(outstanding, gross)))

    # Saved salary no longer matches attendance (days / OT / DA edited after saving)
    stale = bool(existing) and (
        Decimal(existing.paid_days) != s["paid_days"]
        or money(existing.earned) != earned
        or money(existing.ot_amount) != ot_amount
        or money(existing.da_amount) != s["da_amount"]
    )

    return {
        **s,
        "rate": rate,
        "earned": earned,
        "ot_amount": ot_amount,
        "gross": gross,
        "advance_outstanding": money(outstanding),
        "suggested_advance": suggested_adv,
        "existing": existing,
        "stale": stale,
    }
