"""Cut Daily / Weekly / Monthly packs from an in-memory item pool."""

import sys
from datetime import datetime, timezone

from kerning_lib.windows import RECENCY_TAU, edition_meta, expected_periods

DAILY_LIMIT = 4
_WEEKLY_PAYLOAD_KEYS = ("week_start", "week_end", "week_label", "iso_week")


ALL_KINDS = ("daily", "weekly", "monthly")


def keep_previous_packs(cadences, previous, kinds=ALL_KINDS):
    """Any empty pack in kinds takes the previous pack of that kind when it has items."""
    cadences = cadences or {}
    old = (previous or {}).get("cadences") or {}
    merged = None
    for kind in kinds:
        if (cadences.get(kind) or {}).get("items"):
            continue
        old_pack = old.get(kind) or {}
        if not old_pack.get("items"):
            continue
        print("%s: empty cut, keeping previous pack" % kind, file=sys.stderr)
        if merged is None:
            merged = dict(cadences)
        merged[kind] = old_pack
    return cadences if merged is None else merged


def keep_previous_weekly(cadences, previous):
    """If the new weekly pack is empty, keep the previous weekly when it has items."""
    return keep_previous_packs(cadences, previous, kinds=("weekly",))


def apply_kept_weekly(payload, previous):
    """Keep previous weekly on an empty recut, including top-level week fields."""
    return apply_kept_packs(payload, previous, kinds=("weekly",))


def apply_kept_packs(payload, previous, kinds=ALL_KINDS):
    """keep_previous_packs on a digest payload, refreshing top-level weekly fields."""
    if not isinstance(payload, dict):
        return payload
    cadences = payload.get("cadences") or {}
    kept = keep_previous_packs(cadences, previous, kinds=kinds)
    if kept is cadences:
        return payload
    out = dict(payload)
    out["cadences"] = kept
    weekly = kept.get("weekly") or {}
    out["items"] = weekly.get("items") or []
    for key in _WEEKLY_PAYLOAD_KEYS:
        if key in weekly:
            out[key] = weekly[key]
    return out


def cut_cadences(items, weights, skip_urls, now, limit=12, periods=None):
    """Score and cut edition packs from already-merged items. No network."""
    import kerning_fetch as kf

    if isinstance(now, datetime):
        now_dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        now_ts = now_dt.timestamp()
    else:
        now_ts = float(now)
        now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)

    periods = periods or expected_periods(now_dt)
    skip_urls = skip_urls or set()
    weights = weights or {}
    cadences = {}
    for kind, (start, end) in periods.items():
        tau = RECENCY_TAU.get(kind, 7)
        n = 4 if kind == "daily" else limit
        picked = kf.cut_edition(
            items, start.timestamp(), n, weights, now_ts, tau, skip_urls,
            until=end.timestamp(),
        )
        pack = edition_meta(kind, start, end)
        pack["items"] = [kf.serialize_item(it) for it in picked]
        cadences[kind] = pack
    return cadences


def row_to_item(row):
    """Turn a crawl/overlay source row (or a stories-table dict) into a merge item."""
    return {
        "title": row.get("title") or "",
        "url": row.get("url") or "",
        "discussion": row.get("discussion") or row.get("hn") or "",
        "source": row.get("source") or (row.get("sources") or ["unknown"])[0],
        "points": int(row.get("points") or 0),
        "comments": int(row.get("comments") or 0),
        "ts": float(row.get("ts") or row.get("created_at_i") or 0),
        "curated": bool(row.get("curated")),
        "always_relevant": bool(row.get("always_relevant")),
        "authors": list(row.get("authors") or []),
        "sharers": int(row.get("sharers") or 0),
        "share_engagement": int(row.get("share_engagement") or 0),
    }
