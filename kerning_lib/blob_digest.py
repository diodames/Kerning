"""Vercel Blob helpers for the shared public digest.

The static file digest.json cannot be rewritten on Vercel. Recut writes the
new pack here, and GET /api/digest reads it back.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import requests

from kerning_lib.windows import payload_current

BLOB_API = "https://blob.vercel-storage.com"
API_VERSION = "7"
DIGEST_PATH = "kerning/digest.json"
LOCK_PATH = "kerning/rebuild.lock"
LOCK_TTL_SEC = 240
FETCH_TIMEOUT_SEC = 280

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FETCH = os.path.join(_ROOT, "kerning_fetch.py")


def blob_configured():
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN"))


def should_skip_fetch(data, force=False, now=None):
    """True when a recut would not change the calendar windows."""
    if force:
        return False
    return payload_current(data, now)


def lock_is_fresh(lock, now=None):
    """True when another rebuild started recently and may still be running."""
    if not isinstance(lock, dict):
        return False
    started = _parse_ts(lock.get("started_at"))
    if started is None:
        return False
    now = now or datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - started).total_seconds() < LOCK_TTL_SEC


def get_digest_payload():
    if not blob_configured():
        return None
    return _get_json(DIGEST_PATH)


def run_rebuild(force=False):
    """Return (status_code, payload) for POST/GET /api/rebuild."""
    if not blob_configured():
        return 404, {"error": "blob-unconfigured"}

    data = get_digest_payload()
    if should_skip_fetch(data, force=force):
        return 200, {"rebuilt": False}

    lock = _get_json(LOCK_PATH)
    if lock_is_fresh(lock):
        return 202, {"rebuilt": False, "status": "running"}

    _put_json(LOCK_PATH, {"started_at": datetime.now(timezone.utc).isoformat()})
    try:
        out_base = os.path.join("/tmp", "kerning-digest")
        cmd = [
            sys.executable, _FETCH,
            "--limit", "12",
            "--no-x",
            "--out", out_base,
        ]
        run = subprocess.run(cmd, cwd=_ROOT, timeout=FETCH_TIMEOUT_SEC)
        if run.returncode != 0:
            return 500, {"error": "fetch-failed", "code": run.returncode}
        path = out_base + ".json"
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        _put_json(DIGEST_PATH, payload)
        return 200, {"rebuilt": True}
    except subprocess.TimeoutExpired:
        return 504, {"error": "fetch-timeout"}
    except (OSError, ValueError) as e:
        return 500, {"error": str(e)}
    finally:
        _delete(LOCK_PATH)


def _auth_headers():
    return {
        "Authorization": "Bearer " + os.environ["BLOB_READ_WRITE_TOKEN"],
        "x-api-version": API_VERSION,
    }


def _put_headers():
    headers = _auth_headers()
    headers["x-content-type"] = "application/json"
    headers["x-add-random-suffix"] = "0"
    headers["x-allow-overwrite"] = "1"
    headers["x-vercel-blob-access"] = "private"
    headers["x-cache-control-max-age"] = "60"
    return headers


def _get_json(pathname):
    listed = requests.get(
        BLOB_API,
        params={"prefix": pathname, "limit": "10"},
        headers=_auth_headers(),
        timeout=20,
    )
    if listed.status_code == 404:
        return None
    listed.raise_for_status()
    blobs = listed.json().get("blobs") or []
    match = None
    for blob in blobs:
        if blob.get("pathname") == pathname:
            match = blob
            break
    if match is None and blobs:
        match = blobs[0]
    if not match or not match.get("url"):
        return None
    got = requests.get(match["url"], headers=_auth_headers(), timeout=20)
    if got.status_code == 404:
        return None
    got.raise_for_status()
    data = got.json()
    if not isinstance(data, dict):
        return None
    return data


def _put_json(pathname, data):
    resp = requests.put(
        BLOB_API + "/" + pathname,
        headers=_put_headers(),
        data=json.dumps(data).encode("utf-8"),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _delete(pathname):
    listed = requests.get(
        BLOB_API,
        params={"prefix": pathname, "limit": "10"},
        headers=_auth_headers(),
        timeout=20,
    )
    if listed.status_code != 200:
        return
    urls = []
    for blob in listed.json().get("blobs") or []:
        if blob.get("pathname") == pathname and blob.get("url"):
            urls.append(blob["url"])
    if not urls:
        return
    requests.post(
        BLOB_API + "/delete",
        headers=_auth_headers(),
        json={"urls": urls},
        timeout=20,
    )


def _parse_ts(value):
    if not value or not isinstance(value, str):
        return None
    try:
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None
