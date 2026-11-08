from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .. import db
from ..models import Advance, Employee
from ..utils import month_bounds, owner_required, parse_month, to_dec

bp = Blueprint("advances", __name__, url_prefix="/advances")


@bp.route("/", methods=["GET", "POST"])
@login_required
@owner_required
def index():
    if request.method == "POST":
        emp = db.session.get(Employee, request.form.get("employee_id", type=int))
        amount = to_dec(request.form.get("amount"))
        if not emp or amount <= 0:
            flash("Choose an employee and enter an amount greater than 0", "error")
        else:
            d = request.form.get("date")
            adv = Advance(
                employee_id=emp.id,
                amount=amount,
                date=datetime.strptime(d, "%Y-%m-%d").date() if d else date.today(),
                mode=request.form.get("mode", "Cash"),
                reason=request.form.get("reason", "").strip() or None,
            )
            db.session.add(adv)
            db.session.commit()
            flash(f"Advance of ₹{amount} recorded for {emp.name}", "success")
        return redirect(url_for("advances.index", month=request.args.get("month")))

    year, month = parse_month(request.args.get("month"))
    start, end, _ = month_bounds(year, month)
    advances = Advance.query.filter(Advance.date.between(start, end)) \
        .order_by(Advance.date.desc(), Advance.id.desc()).all()
    employees = Employee.query.filter_by(active=True).order_by(Employee.name).all()
    outstanding = [(e, e.advance_outstanding()) for e in Employee.query.order_by(Employee.name).all()]
    outstanding = [(e, o) for e, o in outstanding if o != 0]
    return render_template("advances/index.html", advances=advances, employees=employees,
                           outstanding=outstanding, total=sum(a.amount for a in advances),
                           month_value=f"{year:04d}-{month:02d}",
                           month_label=start.strftime("%B %Y"), today=date.today())


@bp.route("/<int:adv_id>/delete", methods=["POST"])
@login_required
@owner_required
def delete(adv_id):
    adv = db.get_or_404(Advance, adv_id)
    db.session.delete(adv)
    db.session.commit()
    flash("Advance entry deleted", "success")
    return redirect(request.referrer or url_for("advances.index"))


@bp.route("/<int:adv_id>/edit", methods=["GET", "POST"])
@login_required
@owner_required
def edit(adv_id):
    adv = db.get_or_404(Advance, adv_id)
    if request.method == "POST":
        amount = to_dec(request.form.get("amount"))
        if amount <= 0:
            flash("Amount must be greater than 0", "error")
        else:
            adv.amount = amount
            d = request.form.get("date")
            if d:
                adv.date = datetime.strptime(d, "%Y-%m-%d").date()
            adv.mode = request.form.get("mode", adv.mode)
            adv.reason = request.form.get("reason", "").strip() or None
            db.session.commit()
            flash("Advance updated", "success")
            return redirect(request.form.get("next") or url_for("employees.ledger", emp_id=adv.employee_id))
    return render_template("advances/edit.html", adv=adv, next=request.args.get("next", ""))
