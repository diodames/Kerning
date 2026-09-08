"""Shared crawl of public sources into the stories pool. No X/Apify."""

import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

import kerning_fetch as kf
from app import config
from app.db import SessionLocal
from app.models import Story
from kerning_lib.windows import aware_now, this_month


def _utcnow():
    return datetime.now(timezone.utc)


def upsert_rows(db, rows, user_id=None):
    n = 0
    now = _utcnow()
    uid = user_id or ""
    for r in rows:
        url = r.get("url") or ""
        key = kf.canonical(url)
        if not key:
            continue
        existing = db.query(Story).filter(Story.key == key, Story.user_id == uid).one_or_none()
        payload = {
            "title": r.get("title") or "",
            "url": url,
            "discussion": r.get("discussion") or "",
            "source": r.get("source") or "",
            "points": r.get("points") or 0,
            "comments": r.get("comments") or 0,
            "ts": r.get("ts") or 0,
            "curated": bool(r.get("curated")),
            "always_relevant": bool(r.get("always_relevant")),
            "authors": r.get("authors") or [],
            "sharers": r.get("sharers") or 0,
            "share_engagement": r.get("share_engagement") or 0,
        }
        ts = int(payload["ts"] or 0)
        if existing:
            existing.title = payload["title"] or existing.title
            existing.url = url
            existing.payload = payload
            existing.created_at_i = ts or existing.created_at_i
            existing.last_seen = now
        else:
            db.add(Story(
                key=key,
                user_id=uid,
                url=url,
                title=payload["title"],
                payload=payload,
                created_at_i=ts,
                first_seen=now,
                last_seen=now,
            ))
        n += 1
    db.commit()
    return n


def pool_is_fresh(db):
    row = (
        db.query(Story)
        .filter(Story.user_id == "")
        .order_by(Story.last_seen.desc())
        .first()
    )
    if not row or not row.last_seen:
        return False
    seen = row.last_seen
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (_utcnow() - seen) < timedelta(hours=config.POOL_FRESH_HOURS)


def crawl_shared(days=None):
    """Fetch HN, Lobsters, curated RSS, GitHub releases into global stories."""
    now_dt = aware_now()
    month_start, _ = this_month(now_dt)
    days = days if days is not None else max((time.time() - month_start.timestamp()) / 86400, 1 / 24)
    rows = []
    for label, fn in (("hacker news", kf.fetch_hn), ("lobsters", kf.fetch_lobsters)):
        try:
            got = fn(days)
            rows.extend(got)
            print("%s: %s" % (label, len(got)), file=sys.stderr)
        except Exception as e:
            print("%s: failed (%s)" % (label, e), file=sys.stderr)
    try:
        got = kf.fetch_feeds(days, dict(kf.CURATED_FEEDS))
        rows.extend(got)
        print("publications: %s" % len(got), file=sys.stderr)
    except Exception as e:
        print("publications: failed (%s)" % e, file=sys.stderr)
    try:
        got = kf.fetch_releases(days, dict(kf.GITHUB_REPOS))
        rows.extend(got)
        print("design systems: %s" % len(got), file=sys.stderr)
    except Exception as e:
        print("design systems: failed (%s)" % e, file=sys.stderr)

    db = SessionLocal()
    try:
        n = upsert_rows(db, rows, user_id=None)
        print("crawl upserted %s rows" % n, file=sys.stderr)
        return n
    finally:
        db.close()


def pool_items(db, user_id, since_ts=0):
    """Global stories plus this user's overlay, as merge-ready rows."""
    q = db.query(Story).filter(Story.created_at_i >= int(since_ts))
    q = q.filter(or_(Story.user_id == "", Story.user_id == user_id))
    rows = []
    for s in q:
        p = dict(s.payload or {})
        p["url"] = s.url or p.get("url")
        p["title"] = s.title or p.get("title")
        p["ts"] = p.get("ts") or s.created_at_i
        if not p.get("source"):
            p["source"] = "unknown"
        rows.append(p)
    return rows
