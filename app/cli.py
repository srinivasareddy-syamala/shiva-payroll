import click

from . import db
from .models import User


MIGRATIONS = [
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS whatsapp VARCHAR(20)",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS da_amount NUMERIC(10,2) NOT NULL DEFAULT 0",
    "ALTER TABLE salary_payments ADD COLUMN IF NOT EXISTS da_amount NUMERIC(10,2) NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS marked_at TIMESTAMP",
]


def migrate_columns():
    """Add columns introduced after the first release (safe to run every start)."""
    from sqlalchemy import text
    if db.engine.dialect.name != "postgresql":
        return
    with db.engine.begin() as conn:
        for stmt in MIGRATIONS:
            conn.execute(text(stmt))


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all tables."""
        db.create_all()
        migrate_columns()
        click.echo("Tables ready.")

    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("password")
    @click.option("--role", type=click.Choice(["owner", "supervisor"]), default="owner")
    def create_user(username, password, role):
        """Create a login: flask create-user admin secret --role owner"""
        if User.query.filter_by(username=username).first():
            click.echo("User already exists.")
            return
        u = User(username=username, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Created {role} '{username}'.")

    @app.cli.command("ensure-owner")
    def ensure_owner():
        """Create the owner from ADMIN_USER / ADMIN_PASSWORD env vars if no owner exists (used by Docker)."""
        import os
        if User.query.filter_by(role="owner").first():
            click.echo("Owner already exists.")
            return
        username = os.environ.get("ADMIN_USER", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "")
        if len(password) < 6:
            click.echo("No owner yet. Set ADMIN_PASSWORD (min 6 chars) in the environment to create the first owner login.")
            return
        u = User(username=username, role="owner")
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Created owner '{username}'.")
