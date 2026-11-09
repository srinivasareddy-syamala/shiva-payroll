import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()


def _database_url():
    """DATABASE_URL if given (Render etc.), otherwise built from POSTGRES_* parts (docker-compose / Dokploy).
    Building it here means passwords with @ : / # never need manual URL-encoding."""
    url = os.environ.get("DATABASE_URL")
    if not url and os.environ.get("POSTGRES_PASSWORD"):
        url = "postgresql://{u}:{p}@{h}:{port}/{db}".format(
            u=quote(os.environ.get("POSTGRES_USER", "postgres"), safe=""),
            p=quote(os.environ["POSTGRES_PASSWORD"], safe=""),
            h=os.environ.get("POSTGRES_HOST", "localhost"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
            db=os.environ.get("POSTGRES_DB", "shiva_payroll"))
    return url or "postgresql://postgres:postgres@localhost:5432/shiva_payroll"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    _db_url = _database_url()
    # Render gives "postgres://"; use the psycopg 3 driver explicitly
    for _prefix in ("postgres://", "postgresql://"):
        if _db_url.startswith(_prefix):
            _db_url = "postgresql+psycopg://" + _db_url[len(_prefix):]
            break
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER",
                                   os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"))
    MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15 MB per upload
    COMPANY_NAME = os.environ.get("COMPANY_NAME", "Shiva Traders")
    COMPANY_ADDRESS = os.environ.get("COMPANY_ADDRESS", "")
