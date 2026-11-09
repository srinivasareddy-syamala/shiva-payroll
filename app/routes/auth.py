from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .. import db
from ..models import User
from ..utils import owner_required

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username", "").strip()).first()
        if user and not user.active:
            flash("This login is disabled. Ask the owner.", "error")
        elif user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=True)
            return redirect(request.args.get("next") or url_for("main.dashboard"))
        else:
            flash("Invalid username or password", "error")
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/users", methods=["GET", "POST"])
@login_required
@owner_required
def users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "supervisor")
        if not username or len(password) < 6:
            flash("Username required and password must be at least 6 characters", "error")
        elif User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
        else:
            u = User(username=username, role=role)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash(f"User {username} created", "success")
        return redirect(url_for("auth.users"))
    return render_template("users.html", users=User.query.order_by(User.username).all())


@bp.route("/users/<int:uid>", methods=["POST"])
@login_required
@owner_required
def user_update(uid):
    u = db.get_or_404(User, uid)
    action = request.form.get("action")
    if action == "password":
        pw = request.form.get("password", "")
        if len(pw) < 6:
            flash("Password must be at least 6 characters", "error")
        else:
            u.set_password(pw)
            db.session.commit()
            flash(f"Password changed for {u.username}", "success")
    elif action in ("role", "toggle", "delete"):
        if u.id == current_user.id:
            flash("You cannot change your own role, disable or delete yourself", "error")
            return redirect(url_for("auth.users"))
        if action == "role":
            u.role = "owner" if request.form.get("role") == "owner" else "supervisor"
            flash(f"{u.username} is now {u.role}", "success")
        elif action == "toggle":
            u.active = not u.active
            flash(f"{u.username} {'enabled' if u.active else 'disabled'}", "success")
        else:
            from ..models import Attendance, VehicleExpense
            if VehicleExpense.query.filter((VehicleExpense.submitted_by == u.id) | (VehicleExpense.reviewed_by == u.id)).first() \
                    or Attendance.query.filter_by(marked_by=u.id).first():
                u.active = False
                flash(f"{u.username} has attendance/expense records, so the login was disabled instead of deleted", "error")
            else:
                db.session.delete(u)
                flash(f"User {u.username} deleted", "success")
        db.session.commit()
    return redirect(url_for("auth.users"))
