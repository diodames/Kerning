"""GET /api/digest — the digest GitHub Actions commits to the `data` branch."""

from http.server import BaseHTTPRequestHandler
import json
import os
import sys

import requests

DIGEST_URL = os.environ.get(
    "KERNING_DIGEST_URL",
    "https://raw.githubusercontent.com/diodames/Kerning/data/digest.json",
)

# The digest changes once a night; collect runs only touch the pool.
EDGE_CACHE = "public, max-age=60, s-maxage=600, stale-while-revalidate=86400"


def fetch_digest(url=DIGEST_URL):
    r = requests.get(url, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = fetch_digest()
        except Exception as e:
            _send(self, 500, {"error": str(e)})
            return
        if data is None:
            _send(self, 404, {"error": "digest-missing"})
            return
        _send(self, 200, data, cache=EDGE_CACHE)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def _send(http, status, payload, cache="no-store"):
    body = json.dumps(payload).encode("utf-8")
    http.send_response(status)
    http.send_header("Content-Type", "application/json; charset=utf-8")
    http.send_header("Cache-Control", cache)
    http.send_header("Content-Length", str(len(body)))
    http.end_headers()
    http.wfile.write(body)
