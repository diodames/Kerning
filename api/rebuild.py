"""POST /api/rebuild — recut the shared digest into Vercel Blob.

GET is for the Vercel cron (00:20 Prague in summer). Opening the reader POSTs
with { force } and waits. Concurrent opens get 202 and poll GET /api/digest.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from kerning_lib.blob_digest import run_rebuild  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        _rebuild(self, force=False)

    def do_POST(self):
        body = _read_json(self)
        _rebuild(self, force=bool(body.get("force")))

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def _rebuild(http, force):
    try:
        status, payload = run_rebuild(force=force)
    except Exception as e:
        _send(http, 500, {"error": str(e)})
        return
    _send(http, status, payload)


def _read_json(http):
    length = int(http.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = http.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _send(http, status, payload):
    body = json.dumps(payload).encode("utf-8")
    http.send_response(status)
    http.send_header("Content-Type", "application/json; charset=utf-8")
    http.send_header("Cache-Control", "no-store")
    http.send_header("Content-Length", str(len(body)))
    http.end_headers()
    http.wfile.write(body)
