import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    _db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shiva_payroll"
    )
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
