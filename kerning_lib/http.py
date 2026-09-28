"""Tiny helpers for Vercel Python function handlers."""

import json
from urllib.parse import parse_qs, urlparse

from kerning_lib.auth import cron_authorized


def query_params(http):
    parsed = urlparse(http.path or "")
    return {k: (v[-1] if v else "") for k, v in parse_qs(parsed.query).items()}


def read_json_body(http):
    length = int(http.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = http.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def send_json(http, status, payload):
    body = json.dumps(payload).encode("utf-8")
    http.send_response(status)
    http.send_header("Content-Type", "application/json; charset=utf-8")
    http.send_header("Cache-Control", "no-store")
    http.send_header("Content-Length", str(len(body)))
    http.end_headers()
    http.wfile.write(body)


def require_cron(http):
    if cron_authorized(http.headers):
        return True
    send_json(http, 401, {"error": "unauthorized"})
    return False
