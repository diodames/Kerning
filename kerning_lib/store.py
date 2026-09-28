"""Blob or local files for the pool, closed days, and digest cache."""

import json
import os
from datetime import datetime, timezone

from kerning_lib.blob_digest import (
    DIGEST_PATH,
    LOCK_PATH,
    LOCK_TTL_SEC,
    _delete,
    _get_json,
    _put_json,
    blob_configured,
    lock_is_fresh,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DATA = os.path.join(_ROOT, "data")
LOCAL_DIGEST = os.path.join(_ROOT, "digest.json")

POOL_PATH = "kerning/pool.json"
LOCK_COLLECT = "kerning/collect.lock"
LOCK_CLOSE = "kerning/close.lock"


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


def acquire_lock(pathname=LOCK_PATH, ttl=LOCK_TTL_SEC):
    """Return True if this caller holds the lock. False if another run is fresh."""
    lock = get_json(pathname)
    if lock_is_fresh(lock, ttl=ttl):
        return False
    put_json(pathname, {"started_at": datetime.now(timezone.utc).isoformat()})
    return True


def release_lock(pathname=LOCK_PATH):
    delete_json(pathname)
