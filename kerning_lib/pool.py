"""Raw story pool: upsert by canonical URL, 60-day retention."""

from datetime import datetime, timedelta, timezone

from kerning_fetch import canonical
from kerning_lib.windows import POOL_RETENTION_DAYS, prague_date_str, to_prague


def utc_now_iso(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).isoformat()


def empty_pool():
    return {"updated_at": "", "items": {}}


def normalize_pool(data):
    if not isinstance(data, dict):
        return empty_pool()
    items = data.get("items")
    if not isinstance(items, dict):
        items = {}
    return {"updated_at": data.get("updated_at") or "", "items": items}


def row_to_pool_fields(row, now_iso):
    url = row.get("url") or ""
    key = row.get("key") or canonical(url)
    sources = list(row.get("sources") or [])
    source = row.get("source") or (sources[0] if sources else "unknown")
    if source and source not in sources:
        sources.insert(0, source)
    return {
        "key": key,
        "url": url,
        "title": (row.get("title") or "").strip(),
        "discussion": row.get("discussion") or row.get("hn") or "",
        "source": source,
        "sources": sources,
        "points": int(row.get("points") or 0),
        "comments": int(row.get("comments") or 0),
        "ts": float(row.get("ts") or 0),
        "curated": bool(row.get("curated")),
        "always_relevant": bool(row.get("always_relevant")),
        "authors": list(row.get("authors") or []),
        "sharers": int(row.get("sharers") or 0),
        "share_engagement": int(row.get("share_engagement") or 0),
        "first_seen": now_iso,
        "last_seen": now_iso,
    }


def upsert_rows(pool, rows, now=None):
    """Insert or update by canonical URL. first_seen never moves. Returns counts."""
    data = normalize_pool(pool)
    items = data["items"]
    now_iso = utc_now_iso(now)
    inserted = 0
    updated = 0
    for row in rows or []:
        fields = row_to_pool_fields(row, now_iso)
        key = fields["key"]
        if not key:
            continue
        existing = items.get(key)
        if existing is None:
            items[key] = fields
            inserted += 1
            continue
        existing["title"] = fields["title"] or existing.get("title") or ""
        existing["url"] = fields["url"] or existing.get("url") or ""
        existing["discussion"] = fields["discussion"] or existing.get("discussion") or ""
        existing["points"] = fields["points"]
        existing["comments"] = fields["comments"]
        existing["last_seen"] = now_iso
        existing["sharers"] = max(int(existing.get("sharers") or 0), fields["sharers"])
        existing["share_engagement"] = max(
            int(existing.get("share_engagement") or 0), fields["share_engagement"]
        )
        if fields["curated"]:
            existing["curated"] = True
        if fields["always_relevant"]:
            existing["always_relevant"] = True
        merged_sources = list(existing.get("sources") or [])
        for src in fields["sources"]:
            if src and src not in merged_sources:
                merged_sources.append(src)
        existing["sources"] = merged_sources
        if merged_sources:
            existing["source"] = merged_sources[0]
        authors = list(existing.get("authors") or [])
        seen = {str(a).lower() for a in authors}
        for a in fields["authors"]:
            k = str(a).lower()
            if k and k not in seen:
                authors.append(a)
                seen.add(k)
        existing["authors"] = authors
        updated += 1
    data["updated_at"] = now_iso
    data["items"] = items
    return data, inserted, updated


def prune_pool(pool, now=None, days=POOL_RETENTION_DAYS):
    """Drop items whose last_seen is older than days. Closed days are not stored here."""
    data = normalize_pool(pool)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=days)
    kept = {}
    dropped = 0
    for key, item in data["items"].items():
        seen = item.get("last_seen") or item.get("first_seen") or ""
        try:
            ts = datetime.fromisoformat(str(seen).replace("Z", "+00:00"))
        except ValueError:
            ts = cutoff
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < cutoff:
            dropped += 1
            continue
        kept[key] = item
    data["items"] = kept
    return data, dropped


def items_for_prague_date(pool, date_str):
    """Pool items whose first_seen calendar day in Prague is date_str (YYYY-MM-DD)."""
    data = normalize_pool(pool)
    out = []
    for item in data["items"].values():
        first = item.get("first_seen") or ""
        if not first:
            continue
        try:
            if prague_date_str(first) == date_str:
                out.append(item)
        except (ValueError, TypeError):
            continue
    return out


def items_published_on(pool, date_str):
    """Pool items whose publish time (ts) falls on date_str in Prague."""
    data = normalize_pool(pool)
    out = []
    for item in data["items"].values():
        try:
            ts = float(item.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        if prague_date_str(datetime.fromtimestamp(ts, tz=timezone.utc)) == date_str:
            out.append(item)
    return out


def pool_item_to_rank_item(item):
    """Shape expected by kerning_fetch.score / diversify / serialize_item."""
    url = item.get("url") or ""
    key = item.get("key") or canonical(url)
    return {
        "key": key,
        "title": item.get("title") or "",
        "url": url,
        "discussion": item.get("discussion") or "",
        "sources": list(item.get("sources") or [item.get("source") or "unknown"]),
        "points": int(item.get("points") or 0),
        "comments": int(item.get("comments") or 0),
        "ts": float(item.get("ts") or to_prague(item.get("first_seen")).timestamp()),
        "curated": bool(item.get("curated")),
        "always_relevant": bool(item.get("always_relevant")),
        "authors": list(item.get("authors") or []),
        "sharers": int(item.get("sharers") or 0),
        "share_engagement": int(item.get("share_engagement") or 0),
        "_buzz": (0, 0),
    }
