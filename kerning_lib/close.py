"""Phase B: close a Prague calendar day from the pool. No network."""

import sys
from datetime import date as date_cls, datetime, timedelta, timezone
from collections import Counter

import kerning_fetch as kf
from kerning_lib.cut import keep_previous_packs
from kerning_lib.pool import (
    empty_pool,
    items_for_prague_date,
    items_published_on,
    normalize_pool,
    pool_item_to_rank_item,
)
from kerning_lib.quality import load_quality, marketing_weight, quality_reason
from kerning_lib.store import (
    DIGEST_PATH,
    LOCK_CLOSE,
    POOL_PATH,
    acquire_lock,
    day_path,
    get_json,
    put_json,
    release_lock,
    stats_path,
)
from kerning_lib.windows import (
    RECENCY_TAU,
    dates_in_period,
    edition_meta,
    expected_periods,
    prague_date_str,
    prague_tz,
    to_prague,
    yesterday,
)

DAILY_LIMIT = 4
WEEKLY_LIMIT = 12
MONTHLY_LIMIT = 12
DAILY_FALLBACK_DAYS = 7


def _parse_date(value, now=None):
    now = to_prague(now)
    if not value:
        start, _ = yesterday(now)
        return start.date().isoformat()
    text = str(value).strip()
    datetime.strptime(text, "%Y-%m-%d")
    return text


def _day_bounds(date_str):
    """Prague midnight to next Prague midnight for YYYY-MM-DD."""
    d = date_cls.fromisoformat(date_str)
    nxt = d + timedelta(days=1)
    tz = prague_tz()
    return (datetime(d.year, d.month, d.day, tzinfo=tz),
            datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz))


def _filter_and_score(raw_items, cfg, now_ts, tau, limit, skip_keys=None):
    skip_keys = skip_keys or set()
    dropped = []
    ranked = []
    for raw in raw_items:
        item = pool_item_to_rank_item(raw)
        if item["key"] in skip_keys:
            dropped.append({"url": item.get("url") or "", "title": item.get("title") or "",
                            "reason": "already_closed"})
            continue
        reason = quality_reason(item, cfg)
        if reason:
            dropped.append({"url": item.get("url") or "", "title": item.get("title") or "",
                            "reason": reason})
            continue
        if not item.get("always_relevant") and kf.lexicon_score(item["title"], item["url"]) < 2:
            dropped.append({"url": item.get("url") or "", "title": item.get("title") or "",
                            "reason": "lexicon"})
            continue
        scored = kf.score(item, {}, now_ts, tau, set())
        weight = marketing_weight(scored, cfg)
        if weight != 1.0:
            scored["score"] = round(scored["score"] * weight, 3)
        ranked.append(scored)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    kept = kf.diversify(ranked, limit)
    return kept, dropped


def close_day(date_str, pool, cfg, now=None, limit=DAILY_LIMIT, raw=None,
              backfill=False, skip_keys=None):
    """Rank one day's pool items. Returns (day_payload, stats).

    raw defaults to items first seen on date_str, plus items published on
    date_str (so a day that ended before the pool started is not closed
    empty); skip_keys keeps anything already closed out. Backfill passes
    only items published on date_str. Scores are relative to the end of the
    day so days closed late or backfilled rank on the same scale.
    """
    _, day_end = _day_bounds(date_str)
    now_ts = day_end.timestamp()
    if raw is None:
        by_key = {}
        for it in items_for_prague_date(pool, date_str) + items_published_on(pool, date_str):
            by_key.setdefault(it.get("key") or it.get("url"), it)
        raw = list(by_key.values())
    kept, dropped = _filter_and_score(raw, cfg, now_ts, RECENCY_TAU["daily"], limit, skip_keys)
    items = [kf.serialize_item(it) for it in kept]
    reasons = Counter(d["reason"] for d in dropped)
    payload = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    if backfill:
        payload["backfill"] = True
    stats = {
        "date": date_str,
        "pool": len(raw),
        "kept": len(items),
        "dropped": dict(reasons),
        "dropped_items": dropped,
    }
    if backfill:
        stats["backfill"] = True
    return payload, stats


def _window_dates(now):
    periods = expected_periods(now)
    dates = set()
    for kind in ("weekly", "monthly"):
        dates.update(dates_in_period(*periods[kind]))
    return sorted(dates)


def _closed_keys(day):
    if not isinstance(day, dict):
        return set()
    return {kf.canonical(it.get("url") or "") for it in day.get("items") or []}


def backfill_missing_days(pool, cfg, now, before_date):
    """Close missing days in the weekly/monthly windows from publish dates.

    Existing day files are never touched. Days with nothing to keep are not
    written, so a later pool can still fill them. Returns (backfilled dates,
    keys now closed in any window day including before_date).
    """
    dates = _window_dates(now)
    existing = {}
    for d in dates + [before_date]:
        if d in existing:
            continue
        existing[d] = get_json(day_path(d))
    closed = set()
    for day in existing.values():
        closed |= _closed_keys(day)
    done = []
    for d in dates:
        if d >= before_date or existing.get(d) is not None:
            continue
        raw = items_published_on(pool, d)
        if not raw:
            continue
        payload, stats = close_day(d, pool, cfg, raw=raw, backfill=True, skip_keys=closed)
        if not payload["items"]:
            continue
        put_json(day_path(d), payload)
        put_json(stats_path(d), stats)
        closed |= _closed_keys(payload)
        done.append(d)
        print("close: backfilled %s kept=%s" % (d, stats["kept"]), file=sys.stderr)
    return done, closed


def _load_day(date_str, cache):
    if date_str not in cache:
        data = get_json(day_path(date_str))
        cache[date_str] = data if isinstance(data, dict) else None
    return cache[date_str]


def _day_items(date_str, cache):
    return list((_load_day(date_str, cache) or {}).get("items") or [])


def _daily_pack(now, periods, cache):
    """Yesterday's closed day, or the latest non-empty one within a week."""
    start, end = periods["daily"]
    items = _day_items(prague_date_str(start), cache)
    if items:
        pack = edition_meta("daily", start, end)
        pack["items"] = items
        return pack
    for back in range(1, DAILY_FALLBACK_DAYS + 1):
        d = (start.date() - timedelta(days=back)).isoformat()
        items = _day_items(d, cache)
        if items:
            print("daily: yesterday empty, using %s" % d, file=sys.stderr)
            pack = edition_meta("daily", *_day_bounds(d))
            pack["items"] = items
            return pack
    pack = edition_meta("daily", start, end)
    pack["items"] = []
    return pack


def compose_from_days(now=None, previous=None):
    """Weekly and monthly from closed daily files only. Does not read the pool."""
    now = to_prague(now)
    periods = expected_periods(now)
    cache = {}
    cadences = {"daily": _daily_pack(now, periods, cache)}

    for kind, limit in (("weekly", WEEKLY_LIMIT), ("monthly", MONTHLY_LIMIT)):
        start, end = periods[kind]
        seen = {}
        merged = []
        for date_str in dates_in_period(start, end):
            for it in _day_items(date_str, cache):
                url = it.get("url") or ""
                if not url or url in seen:
                    continue
                seen[url] = True
                merged.append(it)
        merged.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        fake = []
        for it in merged:
            fake.append({
                "key": kf.canonical(it.get("url") or ""),
                "url": it.get("url") or "",
                "title": it.get("title") or "",
                "sources": it.get("sources") or ["unknown"],
                "points": it.get("points") or 0,
                "comments": it.get("comments") or 0,
                "score": float(it.get("score") or 0),
            })
        picked = kf.diversify(fake, limit)
        urls = {p["url"] for p in picked}
        items = [it for it in merged if it.get("url") in urls]
        items.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        pack = edition_meta(kind, start, end)
        pack["items"] = items[:limit]
        cadences[kind] = pack

    cadences = keep_previous_packs(cadences, previous)
    weekly = cadences.get("weekly") or {}
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cadence": "weekly",
        "window_days": 7,
        "cadences": cadences,
        "items": weekly.get("items") or [],
    }
    for key in ("week_start", "week_end", "week_label", "iso_week"):
        if key in weekly:
            payload[key] = weekly[key]
    return payload


def run_close(date=None, force=False, now=None):
    """Close one Prague day if missing (or force). Then refresh digest cache."""
    if not acquire_lock(LOCK_CLOSE):
        return {"ok": True, "status": "running", "closed": False}

    try:
        now = to_prague(now)
        date_str = _parse_date(date, now)
        pool = normalize_pool(get_json(POOL_PATH) or empty_pool())
        cfg = load_quality()
        backfilled, closed_keys = backfill_missing_days(pool, cfg, now, date_str)

        existing = get_json(day_path(date_str))
        if existing and existing.get("items") is not None and not force:
            print("close: %s already closed, skip" % date_str, file=sys.stderr)
            previous = get_json(DIGEST_PATH)
            put_json(DIGEST_PATH, compose_from_days(now=now, previous=previous))
            stats = get_json(stats_path(date_str)) or {}
            return {
                "ok": True,
                "closed": False,
                "date": date_str,
                "pool": stats.get("pool") or 0,
                "kept": stats.get("kept") or len(existing.get("items") or []),
                "dropped": stats.get("dropped") or {},
                "backfilled": backfilled,
            }

        skip = closed_keys - _closed_keys(existing) if force else closed_keys
        day_payload, stats = close_day(date_str, pool, cfg, now=now, skip_keys=skip)
        put_json(day_path(date_str), day_payload)
        put_json(stats_path(date_str), stats)
        previous = get_json(DIGEST_PATH)
        put_json(DIGEST_PATH, compose_from_days(now=now, previous=previous))
        print(
            "close: %s pool=%s kept=%s dropped=%s"
            % (date_str, stats["pool"], stats["kept"], stats["dropped"]),
            file=sys.stderr,
        )
        return {
            "ok": True,
            "closed": True,
            "date": date_str,
            "pool": stats["pool"],
            "kept": stats["kept"],
            "dropped": stats["dropped"],
            "backfilled": backfilled,
        }
    finally:
        release_lock(LOCK_CLOSE)
