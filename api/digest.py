"""GET /api/digest — live digest from Vercel Blob."""

from http.server import BaseHTTPRequestHandler
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from kerning_lib.blob_digest import get_digest_payload  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = get_digest_payload()
        except Exception as e:
            _send(self, 500, {"error": str(e)})
            return
        if data is None:
            _send(self, 404, {"error": "digest-missing"})
            return
        _send(self, 200, data)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def _send(http, status, payload):
    body = json.dumps(payload).encode("utf-8")
    http.send_response(status)
    http.send_header("Content-Type", "application/json; charset=utf-8")
    http.send_header("Cache-Control", "no-store")
    http.send_header("Content-Length", str(len(body)))
    http.end_headers()
    http.wfile.write(body)
