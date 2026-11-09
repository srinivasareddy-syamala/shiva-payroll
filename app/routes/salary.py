import calendar
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from urllib.parse import quote

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Employee, SalaryPayment, Setting
from ..payroll import calculate, da_entries
from ..pdf import salary_slip_pdf
from ..utils import can_change, days, inr, money, month_bounds, parse_month, to_dec, today

bp = Blueprint("salary", __name__, url_prefix="/salary")


@bp.route("/", methods=["GET", "POST"])
@login_required
def run():
    year, month = parse_month(request.values.get("month"))
    start, _, _ = month_bounds(year, month)
    employees = Employee.query.filter_by(active=True).order_by(Employee.emp_type, Employee.name).all()

    if request.method == "POST":
        selected = set(request.form.getlist("pay"))
        saved = skipped = 0
        for emp in employees:
            if str(emp.id) not in selected:
                continue
            c = calculate(emp, year, month)
            if c["existing"] and not can_change(c["existing"].paid_on):
                skipped += 1
                continue  # supervisors cannot change salary saved on an earlier day
            bonus = max(to_dec(request.form.get(f"bonus_{emp.id}")), 0)
            adv = to_dec(request.form.get(f"adv_{emp.id}"))
            other = max(to_dec(request.form.get(f"other_{emp.id}")), 0)
            adv = max(Decimal("0"), min(adv, c["advance_outstanding"]))  # never recover more than owed
            net = money(c["earned"] + c["ot_amount"] + c["da_amount"] + bonus - adv - other)
            paid_on = request.form.get("paid_on") if current_user.is_owner else None

            p = c["existing"] or SalaryPayment(employee_id=emp.id, year=year, month=month)
            p.days_in_month = c["days_in_month"]
            p.paid_days = c["paid_days"]
            p.ot_hours = c["ot_hours"]
            p.rate = emp.rate
            p.pay_type = emp.pay_type
            p.earned = c["earned"]
            p.ot_amount = c["ot_amount"]
            p.da_amount = c["da_amount"]
            p.bonus = bonus
            p.advance_deducted = adv
            p.other_deductions = other
            p.net_paid = net
            p.payment_mode = request.form.get(f"mode_{emp.id}", "Cash")
            p.paid_on = datetime.strptime(paid_on, "%Y-%m-%d").date() if paid_on else today()
            p.remarks = request.form.get(f"remarks_{emp.id}", "").strip() or None
            db.session.add(p)
            saved += 1
        db.session.commit()
        flash(f"Salary saved for {saved} employees", "success" if saved else "error")
        if skipped:
            flash(f"{skipped} salary entr{'y' if skipped == 1 else 'ies'} saved on an earlier day {'was' if skipped == 1 else 'were'} not changed (only the owner can change it)", "error")
        return redirect(url_for("salary.run", month=f"{year:04d}-{month:02d}"))

    rows = [(emp, calculate(emp, year, month)) for emp in employees]
    return render_template("salary/run.html", rows=rows, month_value=f"{year:04d}-{month:02d}",
                           month_label=start.strftime("%B %Y"), today=today())


TOTAL_KEYS = ("earned", "ot_amount", "da_amount", "bonus", "advance_deducted", "other_deductions", "net_paid")


def _month_payments(year, month):
    return SalaryPayment.query.filter_by(year=year, month=month).join(Employee) \
        .order_by(Employee.emp_type, Employee.name).all()


@bp.route("/register")
@login_required
def register():
    year, month = parse_month(request.args.get("month"))
    start, _, _ = month_bounds(year, month)
    payments = _month_payments(year, month)
    totals = {k: sum((getattr(p, k) for p in payments), Decimal("0")) for k in TOTAL_KEYS}
    return render_template("salary/register.html", payments=payments, totals=totals,
                           month_value=f"{year:04d}-{month:02d}", month_label=start.strftime("%B %Y"))


@bp.route("/register.xlsx")
@login_required
def register_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    year, month = parse_month(request.args.get("month"))
    payments = _month_payments(year, month)
    wb = Workbook()
    ws = wb.active
    ws.title = f"{year}-{month:02d}"
    headers = ["Name", "Type", "Pay type", "Rate", "Paid days", "OT hrs", "Earned", "OT amt", "DA",
               "Bonus", "Advance ded.", "Other ded.", "Net paid", "Mode", "Paid on"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1E3A8A")
    for p in payments:
        ws.append([p.employee.name, p.employee.emp_type, p.pay_type, float(p.rate), float(p.paid_days),
                   float(p.ot_hours), float(p.earned), float(p.ot_amount), float(p.da_amount), float(p.bonus),
                   float(p.advance_deducted), float(p.other_deductions), float(p.net_paid),
                   p.payment_mode, p.paid_on.strftime("%d-%m-%Y") if p.paid_on else ""])
    n = len(payments) + 1
    ws.append(["TOTAL", "", "", "", "", ""] + [f"=SUM({col}2:{col}{n})" for col in "GHIJKLM"] + ["", ""])
    for c in ws[n + 1]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJKLMNO", [24, 10, 10, 10, 10, 8, 12, 10, 10, 10, 12, 10, 12, 8, 12]):
        ws.column_dimensions[col].width = w
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"salary_register_{year}_{month:02d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _slip_filename(p):
    safe = "".join(ch for ch in p.employee.name if ch.isalnum() or ch in " _-").strip().replace(" ", "_")
    return f"Salary_Slip_{safe}_{calendar.month_abbr[p.month]}_{p.year}.pdf"


@bp.route("/slip/<int:payment_id>.pdf")
@login_required
def slip(payment_id):
    p = db.get_or_404(SalaryPayment, payment_id)
    pdf = salary_slip_pdf(p, Setting.get_all(), da_entries(p.employee, p.year, p.month))
    return send_file(BytesIO(pdf), mimetype="application/pdf", download_name=_slip_filename(p),
                     as_attachment=request.args.get("download") == "1")


def whatsapp_text(p, st):
    emp = p.employee
    lines = [
        f"*{st['company_name']}*",
        f"*Salary Slip — {calendar.month_name[p.month]} {p.year}*",
        "",
        f"Name: {emp.name} ({emp.emp_type})",
        f"Paid days: {days(p.paid_days)} / {p.days_in_month}",
        "",
        f"Basic earned: {inr(p.earned)}",
    ]
    if p.ot_amount:
        lines.append(f"Overtime ({days(p.ot_hours)} h): {inr(p.ot_amount)}")
    if p.da_amount:
        lines.append(f"Day allowance (DA): {inr(p.da_amount)}")
        for a in da_entries(emp, p.year, p.month):
            lines.append(f"   • {a.date.strftime('%d %b')}: {inr(a.da_amount)}" + (f" — {a.remarks}" if a.remarks else ""))
    if p.bonus:
        lines.append(f"Bonus: {inr(p.bonus)}")
    lines.append(f"*Gross: {inr(p.gross)}*")
    if p.advance_deducted:
        lines.append(f"Advance recovered: −{inr(p.advance_deducted)}")
    if p.other_deductions:
        lines.append(f"Other deductions: −{inr(p.other_deductions)}")
    lines += [
        "",
        f"*NET PAID: {inr(p.net_paid)}* ({p.payment_mode}, {p.paid_on.strftime('%d-%m-%Y') if p.paid_on else ''})",
        f"Advance balance remaining: {inr(p.advance_balance_after)}",
    ]
    if st.get("slip_note"):
        lines += ["", st["slip_note"]]
    return "\n".join(lines)


@bp.route("/<int:payment_id>/share")
@login_required
def share(payment_id):
    p = db.get_or_404(SalaryPayment, payment_id)
    st = Setting.get_all()
    text = whatsapp_text(p, st)
    number = p.employee.whatsapp_number
    wa_url = f"https://wa.me/{number}?text={quote(text)}" if number else f"https://wa.me/?text={quote(text)}"
    return render_template("salary/share.html", p=p, text=text, number=number, wa_url=wa_url,
                           filename=_slip_filename(p), back=request.referrer)


@bp.route("/<int:payment_id>/delete", methods=["POST"])
@login_required
def delete(payment_id):
    p = db.get_or_404(SalaryPayment, payment_id)
    if not can_change(p.paid_on):
        flash("Supervisors can delete only salary saved today", "error")
        return redirect(request.referrer or url_for("salary.run"))
    m = f"{p.year:04d}-{p.month:02d}"
    db.session.delete(p)
    db.session.commit()
    flash("Salary entry removed — advance recovery reversed", "success")
    return redirect(request.referrer or url_for("salary.run", month=m))
