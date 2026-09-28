"""POST/GET /api/collect — refresh the raw pool. Protected by CRON_SECRET."""

from http.server import BaseHTTPRequestHandler
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from kerning_lib.collect import run_collect  # noqa: E402
from kerning_lib.http import require_cron, send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        _run(self)

    def do_POST(self):
        _run(self)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def _run(http):
    if not require_cron(http):
        return
    try:
        payload = run_collect()
    except Exception as e:
        send_json(http, 500, {"error": str(e)})
        return
    status = 202 if payload.get("status") == "running" else 200
    send_json(http, status, payload)
