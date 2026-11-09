from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Advance, Employee
from ..utils import can_change, month_bounds, parse_month, to_dec, today

bp = Blueprint("advances", __name__, url_prefix="/advances")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        emp = db.session.get(Employee, request.form.get("employee_id", type=int))
        amount = to_dec(request.form.get("amount"))
        if not emp or amount <= 0:
            flash("Choose an employee and enter an amount greater than 0", "error")
        else:
            d = request.form.get("date") if current_user.is_owner else None
            adv = Advance(
                employee_id=emp.id,
                amount=amount,
                date=datetime.strptime(d, "%Y-%m-%d").date() if d else today(),
                mode=request.form.get("mode", "Cash"),
                reason=request.form.get("reason", "").strip() or None,
            )
            db.session.add(adv)
            db.session.commit()
            flash(f"Advance of ₹{amount} recorded for {emp.name}", "success")
        return redirect(request.full_path if request.query_string else url_for("advances.index"))

    from ..utils import parse_range
    rng = parse_range(request.args, default="this_month")
    emp_id = request.args.get("employee", type=int)
    emp_type, q, mode = request.args.get("type", ""), request.args.get("q", "").strip(), request.args.get("mode", "")
    aq = Advance.query.join(Employee).filter(Advance.date.between(rng["start"], rng["end"]))
    if emp_id:
        aq = aq.filter(Advance.employee_id == emp_id)
    if emp_type in ("Driver", "Worker"):
        aq = aq.filter(Employee.emp_type == emp_type)
    if q:
        aq = aq.filter(Employee.name.ilike(f"%{q}%") | Advance.reason.ilike(f"%{q}%"))
    if mode in ("Cash", "UPI", "Bank"):
        aq = aq.filter(Advance.mode == mode)
    advances = aq.order_by(Advance.date.desc(), Advance.id.desc()).all()
    employees = Employee.query.filter_by(active=True).order_by(Employee.name).all()
    oq = Employee.query
    if emp_id:
        oq = oq.filter(Employee.id == emp_id)
    if emp_type in ("Driver", "Worker"):
        oq = oq.filter(Employee.emp_type == emp_type)
    if q:
        oq = oq.filter(Employee.name.ilike(f"%{q}%"))
    outstanding = [(e, e.advance_outstanding()) for e in oq.order_by(Employee.name).all()]
    outstanding = [(e, o) for e, o in outstanding if o != 0]
    by_emp = {}
    for a in advances:
        by_emp.setdefault(a.employee, [0, 0])
        by_emp[a.employee][0] += 1
        by_emp[a.employee][1] += a.amount
    return render_template("advances/index.html", advances=advances, employees=employees,
                           outstanding=outstanding, total=sum(a.amount for a in advances),
                           rng=rng, emp_id=emp_id, emp_type=emp_type, q=q, mode=mode,
                           by_emp=sorted(by_emp.items(), key=lambda kv: -kv[1][1]),
                           total_outstanding=sum(o for _, o in outstanding), today=today())


@bp.route("/<int:adv_id>/delete", methods=["POST"])
@login_required
def delete(adv_id):
    adv = db.get_or_404(Advance, adv_id)
    if not can_change(adv.date):
        flash("Supervisors can delete only today's advances", "error")
        return redirect(request.referrer or url_for("advances.index"))
    db.session.delete(adv)
    db.session.commit()
    flash("Advance entry deleted", "success")
    return redirect(request.referrer or url_for("advances.index"))


@bp.route("/<int:adv_id>/edit", methods=["GET", "POST"])
@login_required
def edit(adv_id):
    adv = db.get_or_404(Advance, adv_id)
    if not can_change(adv.date):
        flash("Supervisors can change only today's advances", "error")
        return redirect(request.args.get("next") or url_for("employees.ledger", emp_id=adv.employee_id))
    if request.method == "POST":
        amount = to_dec(request.form.get("amount"))
        if amount <= 0:
            flash("Amount must be greater than 0", "error")
        else:
            adv.amount = amount
            d = request.form.get("date")
            if d and current_user.is_owner:
                adv.date = datetime.strptime(d, "%Y-%m-%d").date()
            adv.mode = request.form.get("mode", adv.mode)
            adv.reason = request.form.get("reason", "").strip() or None
            db.session.commit()
            flash("Advance updated", "success")
            return redirect(request.form.get("next") or url_for("employees.ledger", emp_id=adv.employee_id))
    return render_template("advances/edit.html", adv=adv, next=request.args.get("next", ""))
