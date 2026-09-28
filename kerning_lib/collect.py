"""Phase A: fetch sources into the raw pool. No ranking, no quality filter."""

import json
import os
import sys
import time

from kerning_fetch import (
    CURATED_FEEDS,
    GITHUB_REPOS,
    apply_profile_follows,
    apply_profile_resources,
    fetch_bluesky,
    fetch_feeds,
    fetch_hn,
    fetch_lobsters,
    fetch_releases,
    fetch_substack,
    load_bsky_accounts,
    load_substack_pubs,
    merge,
)
from kerning_lib.pool import empty_pool, normalize_pool, prune_pool, upsert_rows
from kerning_lib.store import (
    LOCK_COLLECT,
    POOL_PATH,
    acquire_lock,
    get_json,
    put_json,
    release_lock,
)
from kerning_lib.windows import this_month, to_prague

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECT_DAYS = 4
COLLECT_LOCK_TTL = 320


def _profile_data(path="kerning-profile.json"):
    full = path if os.path.isabs(path) else os.path.join(_ROOT, path)
    if not os.path.isfile(full):
        return {}
    try:
        with open(full, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def fetch_source_rows(days=COLLECT_DAYS, no_bluesky=False, no_substack=False):
    """Download current snapshots. Does not filter or rank."""
    profile_data = _profile_data()
    bsky_accounts = []
    bsky_path = os.path.join(_ROOT, "bsky-accounts.txt")
    if os.path.exists(bsky_path):
        bsky_accounts = load_bsky_accounts(bsky_path)
    substack_pubs = []
    sub_path = os.path.join(_ROOT, "substack.txt")
    catalog = bool(((profile_data or {}).get("seeds") or {}).get("resourcesCatalog"))
    if catalog:
        substack_pubs = []
    elif os.path.exists(sub_path):
        substack_pubs = load_substack_pubs(sub_path)
    apply_profile_follows(profile_data, [], bsky_accounts, substack_pubs)
    feeds = {} if catalog else dict(CURATED_FEEDS)
    repos = {} if catalog else dict(GITHUB_REPOS)
    apply_profile_resources(profile_data, feeds, repos, substack_pubs)

    rows = []
    for label, fn in (("hacker news", fetch_hn), ("lobsters", fetch_lobsters)):
        try:
            got = fn(days)
            rows.extend(got)
            print("%s: %s" % (label, len(got)), file=sys.stderr)
        except Exception as e:
            print("%s: failed (%s)" % (label, e), file=sys.stderr)
    for label, fn, arg in (
        ("publications", fetch_feeds, feeds),
        ("design systems", fetch_releases, repos),
    ):
        try:
            got = fn(days, arg)
            rows.extend(got)
            print("%s: %s" % (label, len(got)), file=sys.stderr)
        except Exception as e:
            print("%s: failed (%s)" % (label, e), file=sys.stderr)
    if not no_bluesky:
        try:
            got, _buzz = fetch_bluesky(days, bsky_accounts)
            rows.extend(got)
            print("bluesky: %s" % len(got), file=sys.stderr)
        except Exception as e:
            print("bluesky: failed (%s)" % (e,), file=sys.stderr)
    if not no_substack:
        try:
            got = fetch_substack(days, substack_pubs)
            rows.extend(got)
            print("substack: %s posts" % len(got), file=sys.stderr)
        except Exception as e:
            print("substack: failed (%s)" % (e,), file=sys.stderr)
    return rows


def run_collect(days=None, now=None):
    """Fetch, merge, upsert. Idempotent. Returns a JSON-serializable dict."""
    if not acquire_lock(LOCK_COLLECT, ttl=COLLECT_LOCK_TTL):
        return {"ok": True, "status": "running", "collected": False}

    try:
        now = now or time.time()
        now_dt = to_prague()
        month_start, _ = this_month(now_dt)
        if days is None:
            days = max((now_dt.timestamp() - month_start.timestamp()) / 86400, COLLECT_DAYS)
            days = min(max(days, COLLECT_DAYS), 40)

        rows = fetch_source_rows(days)
        merged = merge(rows) if rows else []
        pool = normalize_pool(get_json(POOL_PATH) or empty_pool())
        pool, inserted, updated = upsert_rows(pool, merged, now=now_dt)
        pool, pruned = prune_pool(pool, now=now_dt)
        put_json(POOL_PATH, pool)
        print(
            "collect: upserted %s new, %s updated, pruned %s, pool %s"
            % (inserted, updated, pruned, len(pool["items"])),
            file=sys.stderr,
        )
        return {
            "ok": True,
            "collected": True,
            "fetched": len(rows),
            "merged": len(merged),
            "inserted": inserted,
            "updated": updated,
            "pruned": pruned,
            "pool": len(pool["items"]),
        }
    finally:
        release_lock(LOCK_COLLECT)
