#!/usr/bin/env python3
"""
Serve the Kerning reading app and rebuild digest.json when Daily, Weekly,
or Monthly have gone stale.

    python3 kerning_serve.py
    python3 kerning_serve.py --port 8000

POST /rebuild (localhost only) runs kerning_fetch.py --if-stale and waits.
Opening the app calls that route, so a new day gets yesterday’s four without
a manual fetch.
"""

import argparse
import json
import os
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_FETCH = os.path.join(_HERE, "kerning_fetch.py")
_DIGEST = os.path.join(_HERE, "digest.json")

from kerning_fetch import digest_current  # noqa: E402


def _is_loopback(host):
    return host in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1")


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/rebuild":
            self.send_error(404)
            return
        if not _is_loopback(self.client_address[0]):
            self.send_error(403, "rebuild is local only")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        try:
            payload = rebuild()
        except Exception as e:
            self._json(500, {"rebuilt": False, "error": str(e)})
            return
        self._json(200, payload)

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def rebuild():
    if digest_current(_DIGEST):
        return {"rebuilt": False}
    run = subprocess.run(
        [sys.executable, _FETCH, "--limit", "12", "--if-stale"],
        cwd=_HERE,
    )
    if run.returncode != 0:
        raise RuntimeError("kerning_fetch.py exited %s" % run.returncode)
    return {"rebuilt": True}


def main():
    ap = argparse.ArgumentParser(description="Serve Kerning and rebuild a stale digest.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--bind", default="127.0.0.1")
    args = ap.parse_args()
    handler = partial(Handler, directory=_HERE)
    httpd = ThreadingHTTPServer((args.bind, args.port), handler)
    print("Kerning at http://%s:%s/index.html" % (args.bind, args.port),
          file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
