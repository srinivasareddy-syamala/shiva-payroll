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
    """Suggested salary for a calendar month (kept for compatibility)."""
    start, end, _ = month_bounds(year, month)
    return calculate_period(employee, start, end)


def _calculate_month_old(employee, year, month):
    """(old monthly implementation, unused)"""
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


# ---------- Any period (week / custom dates / month) ----------

def summary_range(employee, start, end):
    import calendar as _cal
    recs = Attendance.query.filter(Attendance.employee_id == employee.id,
                                   Attendance.date.between(start, end)).all()
    counts = {k: 0 for k in ATTENDANCE_STATUSES}
    ot = da = Decimal("0")
    monthly_earned = Decimal("0")
    rate = Decimal(employee.rate)
    for r in recs:
        counts[r.status] += 1
        ot += Decimal(r.ot_hours or 0)
        da += Decimal(r.da_amount or 0)
        w = ATTENDANCE_STATUSES[r.status][1]
        if w:
            monthly_earned += rate / _cal.monthrange(r.date.year, r.date.month)[1] * w
    paid_days = sum(Decimal(counts[k]) * ATTENDANCE_STATUSES[k][1] for k in counts)
    return {
        "counts": counts, "paid_days": paid_days, "ot_hours": ot, "da_amount": money(da),
        "da_days": sum(1 for r in recs if r.da_amount and r.da_amount > 0),
        "days_in_month": (end - start).days + 1,      # days in the period
        "marked_days": len(recs), "_monthly_earned": monthly_earned,
    }


def da_entries_range(employee, start, end):
    return Attendance.query.filter(Attendance.employee_id == employee.id, Attendance.date.between(start, end),
                                   Attendance.da_amount > 0).order_by(Attendance.date).all()


def calculate_period(employee, start, end):
    """Suggested salary for start..end (not saved). Monthly salaries are paid per day
    (monthly rate ÷ days in that month), daily wages = rate × paid days."""
    s = summary_range(employee, start, end)
    rate = Decimal(employee.rate)
    earned = s.pop("_monthly_earned") if employee.pay_type == "Monthly" else rate * s["paid_days"]
    ot_amount = Decimal(employee.ot_rate) * s["ot_hours"]
    earned, ot_amount = money(earned), money(ot_amount)

    existing = SalaryPayment.query.filter_by(employee_id=employee.id, period_start=start, period_end=end).first()
    overlap = SalaryPayment.query.filter(SalaryPayment.employee_id == employee.id,
                                         SalaryPayment.period_start <= end, SalaryPayment.period_end >= start,
                                         SalaryPayment.id != (existing.id if existing else 0)).first()
    outstanding = employee.advance_due_for_period(start, end, exclude_payment_id=existing.id if existing else None)
    from .models import Advance
    adv_rows = Advance.query.filter(Advance.employee_id == employee.id, Advance.date.between(start, end)).all()
    s["advance_taken"] = money(sum((a.amount for a in adv_rows), Decimal(0)))
    s["advance_taken_count"] = len(adv_rows)
    gross = earned + ot_amount + s["da_amount"]
    suggested_adv = money(max(Decimal("0"), min(outstanding, gross)))
    stale = bool(existing) and (
        Decimal(existing.paid_days) != s["paid_days"] or money(existing.earned) != earned
        or money(existing.ot_amount) != ot_amount or money(existing.da_amount) != s["da_amount"])
    return {**s, "rate": rate, "earned": earned, "ot_amount": ot_amount, "gross": gross,
            "advance_outstanding": money(outstanding), "suggested_advance": suggested_adv,
            "existing": existing, "overlap": overlap, "stale": stale}
