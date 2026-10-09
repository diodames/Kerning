"""Local files or Blob for the pool, closed days, and digest cache.

KERNING_DATA_DIR wins over Blob: GitHub Actions points it at a checkout of
the `data` branch and commits the result. Without it, Blob is used when a
token is set, else the repo's data/ and digest.json.

No lock files: GitHub Actions concurrency keeps runs from overlapping, and
close writes are idempotent.
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


def _data_dir():
    return os.environ.get("KERNING_DATA_DIR") or ""


def _use_blob():
    return blob_configured() and not _data_dir()


def _local_file(pathname):
    root = _data_dir()
    if pathname == DIGEST_PATH:
        return os.path.join(root, "digest.json") if root else LOCAL_DIGEST
    return os.path.join(root or LOCAL_DATA, pathname.replace("kerning/", "", 1))


def get_json(pathname):
    if _use_blob():
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
    if _use_blob():
        return _put_json(pathname, data)
    path = _local_file(pathname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return {"pathname": pathname}


def delete_json(pathname):
    if _use_blob():
        _delete(pathname)
        return
    path = _local_file(pathname)
    try:
        os.unlink(path)
    except OSError:
        pass
