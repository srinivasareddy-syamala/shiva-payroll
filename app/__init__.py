from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "error"


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    from . import models  # noqa: F401
    from .routes import auth, main, employees, attendance, advances, salary, settings, vehicles

    for bp in (auth.bp, main.bp, employees.bp, attendance.bp, advances.bp, salary.bp, settings.bp, vehicles.bp):
        app.register_blueprint(bp)

    from .cli import register_cli
    register_cli(app)

    from .utils import inr, days, localtime, today
    app.jinja_env.filters["inr"] = inr
    app.jinja_env.filters["days"] = days
    app.jinja_env.filters["localtime"] = localtime
    app.jinja_env.globals["local_today"] = today

    @app.context_processor
    def inject_company():
        from .models import Setting
        from flask_login import current_user
        from .models import VehicleExpense
        st = Setting.get_all()
        pending = 0
        try:
            if current_user.is_authenticated and current_user.is_owner:
                pending = VehicleExpense.query.filter_by(status="Pending").count()
        except Exception:
            db.session.rollback()
        return {"company_name": st["company_name"], "settings": st, "pending_approvals": pending}

    return app
