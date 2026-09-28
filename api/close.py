"""POST/GET /api/close — daily close from the pool. Protected by CRON_SECRET.

GET is for the Vercel cron (23:05 UTC = after Prague midnight year-round).
POST may pass { date, force } to regenerate a closed day.
"""

from http.server import BaseHTTPRequestHandler
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from kerning_lib.close import run_close  # noqa: E402
from kerning_lib.http import query_params, read_json_body, require_cron, send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = query_params(self)
        _run(self, date=q.get("date"), force=q.get("force") in ("1", "true", "yes"))

    def do_POST(self):
        q = query_params(self)
        body = read_json_body(self)
        force = bool(body.get("force")) or q.get("force") in ("1", "true", "yes")
        _run(self, date=body.get("date") or q.get("date"), force=force)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def _run(http, date=None, force=False):
    if not require_cron(http):
        return
    try:
        payload = run_close(date=date, force=force)
    except Exception as e:
        send_json(http, 500, {"error": str(e)})
        return
    status = 202 if payload.get("status") == "running" else 200
    send_json(http, status, payload)
