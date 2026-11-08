from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Setting
from ..utils import owner_required

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
@login_required
@owner_required
def index():
    if request.method == "POST":
        if request.form.get("form") == "company":
            for key in ("company_name", "company_address", "company_phone", "slip_note"):
                Setting.set(key, request.form.get(key, "").strip())
            db.session.commit()
            flash("Company details saved", "success")
        elif request.form.get("form") == "password":
            if not current_user.check_password(request.form.get("current", "")):
                flash("Current password is wrong", "error")
            elif len(request.form.get("new", "")) < 6:
                flash("New password must be at least 6 characters", "error")
            elif request.form.get("new") != request.form.get("confirm"):
                flash("New passwords do not match", "error")
            else:
                current_user.set_password(request.form["new"])
                db.session.commit()
                flash("Password changed", "success")
        return redirect(url_for("settings.index"))
    return render_template("settings.html", st=Setting.get_all())
