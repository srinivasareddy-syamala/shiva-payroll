from datetime import date
from decimal import Decimal

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from .. import db
from ..models import Advance, Attendance, Employee, SalaryPayment
from ..utils import month_bounds, today

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def dashboard():
    td = today()
    start, end, _ = month_bounds(td.year, td.month)
    active = Employee.query.filter_by(active=True).count()
    marked_today = Attendance.query.filter_by(date=td).count()
    present_today = Attendance.query.filter(Attendance.date == td,
                                            Attendance.status.in_(["P", "H"])).count()
    stats = {"active": active, "marked_today": marked_today, "present_today": present_today}
    from datetime import timedelta
    wk = td - timedelta(days=td.weekday())
    stats["week_start"] = wk
    stats["worked_week"] = db.session.query(func.count(func.distinct(Attendance.employee_id))) \
        .filter(Attendance.date.between(wk, td), Attendance.status.in_(["P", "H"])).scalar()
    stats["da_week"] = db.session.query(func.coalesce(func.sum(Attendance.da_amount), 0)) \
        .filter(Attendance.date.between(wk, td)).scalar()
    stats["advances_week"] = db.session.query(func.coalesce(func.sum(Advance.amount), 0)) \
        .filter(Advance.date.between(wk, td)).scalar()

    if True:
        stats["advances_month"] = db.session.query(func.coalesce(func.sum(Advance.amount), 0)) \
            .filter(Advance.date.between(start, end)).scalar()
        stats["salary_month"] = db.session.query(func.coalesce(func.sum(SalaryPayment.net_paid), 0)) \
            .filter_by(year=td.year, month=td.month).scalar()
        total_adv = db.session.query(func.coalesce(func.sum(Advance.amount), 0)).scalar()
        total_rec = db.session.query(func.coalesce(func.sum(SalaryPayment.advance_deducted), 0)).scalar()
        stats["advance_outstanding"] = Decimal(total_adv) - Decimal(total_rec)
        stats["recent_advances"] = Advance.query.order_by(Advance.date.desc(), Advance.id.desc()).limit(5).all()

    return render_template("dashboard.html", stats=stats, today=td)


@bp.app_errorhandler(403)
def forbidden(_e):
    return render_template("403.html"), 403


@bp.route("/home")
def home():
    return redirect(url_for("main.dashboard"))
