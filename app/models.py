from datetime import date, datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager


def _today():
    from .utils import today
    return today()

# ---------- Users ----------

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="supervisor")  # owner | supervisor
    active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_owner(self):
        return self.role == "owner"


@login_manager.user_loader
def load_user(user_id):
    u = db.session.get(User, int(user_id))
    return u if u and u.active else None


# ---------- Employees ----------

class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15))
    whatsapp = db.Column(db.String(20))  # if empty, phone is used
    emp_type = db.Column(db.String(20), nullable=False, default="Worker")  # Driver | Worker
    pay_type = db.Column(db.String(20), nullable=False, default="Monthly")  # Monthly | Daily
    rate = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # monthly salary or daily wage
    ot_rate = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # per overtime hour
    vehicle_no = db.Column(db.String(20))
    joining_date = db.Column(db.Date, default=_today)
    active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    attendance = db.relationship("Attendance", backref="employee", lazy="dynamic",
                                 cascade="all, delete-orphan")
    advances = db.relationship("Advance", backref="employee", lazy="dynamic",
                               cascade="all, delete-orphan")
    payments = db.relationship("SalaryPayment", backref="employee", lazy="dynamic",
                               cascade="all, delete-orphan")

    def advance_outstanding(self, exclude_payment_id=None):
        """Total advances given minus total recovered through salary."""
        given = db.session.query(func.coalesce(func.sum(Advance.amount), 0)) \
            .filter(Advance.employee_id == self.id).scalar()
        q = db.session.query(func.coalesce(func.sum(SalaryPayment.advance_deducted), 0)) \
            .filter(SalaryPayment.employee_id == self.id)
        if exclude_payment_id:
            q = q.filter(SalaryPayment.id != exclude_payment_id)
        recovered = q.scalar()
        return Decimal(given) - Decimal(recovered)

    def advance_due_for_month(self, year, month):
        """Advance owed when paying salary for (year, month): advances given up to that
        month's end minus recoveries in salary of EARLIER months."""
        import calendar as _cal
        month_end = date(year, month, _cal.monthrange(year, month)[1])
        given = db.session.query(func.coalesce(func.sum(Advance.amount), 0)) \
            .filter(Advance.employee_id == self.id, Advance.date <= month_end).scalar()
        recovered = db.session.query(func.coalesce(func.sum(SalaryPayment.advance_deducted), 0)) \
            .filter(SalaryPayment.employee_id == self.id,
                    (SalaryPayment.year * 100 + SalaryPayment.month) < year * 100 + month).scalar()
        return Decimal(given) - Decimal(recovered)

    @property
    def whatsapp_number(self):
        """Digits in international format for wa.me (assumes India +91 for 10-digit numbers)."""
        raw = "".join(ch for ch in (self.whatsapp or self.phone or "") if ch.isdigit())
        if len(raw) == 11 and raw.startswith("0"):
            raw = raw[1:]
        if len(raw) == 10:
            raw = "91" + raw
        return raw if len(raw) >= 11 else None


# ---------- Attendance ----------

ATTENDANCE_STATUSES = {
    "P": ("Present", Decimal("1")),
    "H": ("Half day", Decimal("0.5")),
    "A": ("Absent", Decimal("0")),
    "L": ("Paid leave", Decimal("1")),   # counts as paid day
}


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (db.UniqueConstraint("employee_id", "date", name="uq_attendance_emp_date"),)
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(1), nullable=False, default="P")
    ot_hours = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    da_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # day allowance (long trips etc.)
    remarks = db.Column(db.String(200))
    marked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    marked_at = db.Column(db.DateTime)  # UTC time the entry was last saved
    marker = db.relationship("User", foreign_keys=[marked_by])


# ---------- Advances ----------

class Advance(db.Model):
    __tablename__ = "advances"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, default=_today)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    mode = db.Column(db.String(20), default="Cash")
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------- Salary ----------

class SalaryPayment(db.Model):
    __tablename__ = "salary_payments"
    __table_args__ = (db.UniqueConstraint("employee_id", "year", "month", name="uq_salary_emp_month"),)
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    days_in_month = db.Column(db.Integer, nullable=False)
    paid_days = db.Column(db.Numeric(5, 1), nullable=False, default=0)
    ot_hours = db.Column(db.Numeric(6, 2), nullable=False, default=0)
    rate = db.Column(db.Numeric(10, 2), nullable=False)
    pay_type = db.Column(db.String(20), nullable=False)
    earned = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    ot_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    da_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    bonus = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    advance_deducted = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    other_deductions = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    net_paid = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    payment_mode = db.Column(db.String(20), default="Cash")  # Cash | UPI | Bank
    paid_on = db.Column(db.Date, default=_today)
    remarks = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def gross(self):
        return self.earned + self.ot_amount + self.da_amount + self.bonus

    @property
    def total_deductions(self):
        return self.advance_deducted + self.other_deductions

    @property
    def advance_balance_after(self):
        return self.employee.advance_due_for_month(self.year, self.month) - self.advance_deducted


# ---------- Settings (company details editable in the app) ----------

class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

    DEFAULTS = {"company_name": None, "company_address": "", "company_phone": "", "slip_note": ""}

    @classmethod
    def get_all(cls):
        from flask import current_app
        vals = dict(cls.DEFAULTS)
        vals["company_name"] = current_app.config["COMPANY_NAME"]
        vals["company_address"] = current_app.config["COMPANY_ADDRESS"]
        try:
            for row in cls.query.all():
                if row.value is not None:
                    vals[row.key] = row.value
        except Exception:
            db.session.rollback()
        return vals

    @classmethod
    def set(cls, key, value):
        row = db.session.get(cls, key) or cls(key=key)
        row.value = value
        db.session.add(row)


# ---------- Vehicles ----------

EXPENSE_CATEGORIES = {
    "Diesel": "⛽",
    "Repair": "🔧",
    "Loading": "🐔",   # labour cost for lifting birds into vehicles
    "Other": "🧾",
}


class Vehicle(db.Model):
    __tablename__ = "vehicles"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(30), default="Truck")
    model = db.Column(db.String(60))
    capacity = db.Column(db.String(40))           # e.g. "1500 birds" / "7 ton"
    driver_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    driver = db.relationship("Employee")
    expenses = db.relationship("VehicleExpense", backref="vehicle", lazy="dynamic",
                               cascade="all, delete-orphan")


class VehicleExpense(db.Model):
    __tablename__ = "vehicle_expenses"
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, default=_today, index=True)
    category = db.Column(db.String(20), nullable=False)          # Diesel | Repair | Loading | Other
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    litres = db.Column(db.Numeric(8, 2))                         # diesel
    odometer = db.Column(db.Integer)                             # km reading at fill / repair
    birds = db.Column(db.Integer)                                # loading: birds lifted
    labourers = db.Column(db.Integer)                            # loading: number of workers
    bill_no = db.Column(db.String(40))
    vendor = db.Column(db.String(100))                           # bunk / garage / place
    description = db.Column(db.String(300))
    payment_mode = db.Column(db.String(20), default="Cash")
    slip_file = db.Column(db.String(120))                        # uploaded bill photo / pdf
    driver_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    status = db.Column(db.String(10), nullable=False, default="Pending", index=True)  # Pending|Approved|Rejected
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    review_note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    driver = db.relationship("Employee")
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    @property
    def rate_per_litre(self):
        if self.litres:
            return (Decimal(self.amount) / Decimal(self.litres)).quantize(Decimal("0.01"))
        return None
