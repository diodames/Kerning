"""Blob or local files for the pool, closed days, and digest cache.

No lock files: each lock was a put plus a delete per run, and Hobby Blob
counts puts against a small monthly allowance. GitHub Actions concurrency
keeps collect runs from overlapping; close writes are idempotent.
"""

import json
import os

from kerning_lib.blob_digest import (
    DIGEST_PATH,
    _delete,
    _get_json,
    _put_json,
    blob_configured,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DATA = os.path.join(_ROOT, "data")
LOCAL_DIGEST = os.path.join(_ROOT, "digest.json")

POOL_PATH = "kerning/pool.json"
DAYS_INDEX_PATH = "kerning/days/index.json"


def day_path(date_str):
    return "kerning/days/%s.json" % date_str


def stats_path(date_str):
    return "kerning/days/%s.stats.json" % date_str


def _local_file(pathname):
    if pathname == DIGEST_PATH:
        return LOCAL_DIGEST
    return os.path.join(LOCAL_DATA, pathname.replace("kerning/", "", 1))


def get_json(pathname):
    if blob_configured():
        return _get_json(pathname)
    path = _local_file(pathname)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def put_json(pathname, data):
    if blob_configured():
        return _put_json(pathname, data)
    path = _local_file(pathname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return {"pathname": pathname}


def delete_json(pathname):
    if blob_configured():
        _delete(pathname)
        return
    path = _local_file(pathname)
    try:
        os.unlink(path)
    except OSError:
        pass
