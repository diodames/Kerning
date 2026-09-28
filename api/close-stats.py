"""GET /api/close-stats — drop reasons for a closed day. Protected by CRON_SECRET."""

from http.server import BaseHTTPRequestHandler
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from kerning_lib.close import _parse_date  # noqa: E402
from kerning_lib.http import query_params, require_cron, send_json  # noqa: E402
from kerning_lib.store import get_json, stats_path  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not require_cron(self):
            return
        q = query_params(self)
        try:
            date_str = _parse_date(q.get("date"))
        except ValueError:
            send_json(self, 400, {"error": "bad-date"})
            return
        data = get_json(stats_path(date_str))
        if data is None:
            send_json(self, 404, {"error": "stats-missing", "date": date_str})
            return
        send_json(self, 200, data)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
