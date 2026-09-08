import os
from urllib.parse import urlparse

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(name, default=""):
    return os.environ.get(name, default)


SECRET_KEY = _env("SECRET_KEY", "kerning-dev-secret-change-me")
DATABASE_URL = _env("DATABASE_URL", "sqlite:///" + os.path.join(_HERE, "kerning.db"))
APP_ORIGIN = _env("APP_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
RESEND_API_KEY = _env("RESEND_API_KEY")
MAIL_FROM = _env("MAIL_FROM", "Kerning <noreply@localhost>")
DEFAULT_TZ = _env("DEFAULT_TZ", "Europe/Prague")
PEOPLE_CAP = int(_env("PEOPLE_CAP", "80"))
RESOURCE_CAP = int(_env("RESOURCE_CAP", "40"))
POOL_FRESH_HOURS = float(_env("POOL_FRESH_HOURS", "6"))
SESSION_DAYS = 30
MAGIC_MINUTES = 20


def is_dev_origin(origin=None):
    """True for loopback origins where a magic-link token may appear in the API."""
    host = urlparse(origin or APP_ORIGIN).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1")
