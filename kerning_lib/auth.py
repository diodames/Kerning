"""Bearer CRON_SECRET for collect/close endpoints."""

import os


def cron_secret():
    return (os.environ.get("CRON_SECRET") or "").strip()


def cron_authorized(headers):
    """True when Authorization is Bearer ${CRON_SECRET}."""
    secret = cron_secret()
    if not secret:
        return False
    raw = ""
    if headers is None:
        return False
    if hasattr(headers, "get"):
        raw = headers.get("Authorization") or headers.get("authorization") or ""
    return str(raw).strip() == "Bearer " + secret
