"""Enqueue and run crawl / per-user cut jobs."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app import config
from app.db import SessionLocal
from app.models import FeedCache, Job, Profile, User, UserDigest
from kerning_lib.windows import aware_now, cadences_current, this_month


def _utcnow():
    return datetime.now(timezone.utc)


def _as_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def enqueue(db, kind, user_id=None, delay_seconds=0, force_soon=False, force=False):
    q = db.query(Job).filter(Job.kind == kind, Job.status.in_(("queued", "running")))
    if user_id:
        q = q.filter(Job.user_id == user_id)
    else:
        q = q.filter(Job.user_id.is_(None))
    existing = q.order_by(Job.created_at.desc()).first()
    if existing:
        if force:
            existing.force = 1
        if force_soon and existing.status == "queued":
            existing.not_before = _utcnow()
            db.commit()
        elif force:
            db.commit()
        return existing
    job = Job(
        kind=kind,
        user_id=user_id,
        status="queued",
        force=1 if force else 0,
        not_before=_utcnow() + timedelta(seconds=delay_seconds),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def recover_stuck(db, minutes=10):
    cutoff = _utcnow() - timedelta(minutes=minutes)
    changed = 0
    for job in db.query(Job).filter(Job.status == "running"):
        locked = _as_utc(job.locked_at)
        if locked is None or locked < cutoff:
            job.status = "queued"
            job.locked_at = None
            changed += 1
    if changed:
        db.commit()
    return changed


def claim_one(db):
    now = _utcnow()
    if config.DATABASE_URL.startswith("postgresql"):
        row = db.execute(
            text(
                "SELECT id FROM jobs WHERE status = 'queued' AND not_before <= :now "
                "ORDER BY created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1"
            ),
            {"now": now},
        ).first()
        if not row:
            return None
        job = db.get(Job, row[0])
    else:
        job = None
        for cand in (
            db.query(Job)
            .filter(Job.status == "queued")
            .order_by(Job.created_at.asc())
            .all()
        ):
            if _as_utc(cand.not_before) <= now:
                job = cand
                break
    if not job:
        return None
    job.status = "running"
    job.locked_at = now
    db.commit()
    return job


def _fresh_handles(db, kind, handles):
    cutoff = _utcnow() - timedelta(hours=config.POOL_FRESH_HOURS)
    fresh = set()
    for h in handles:
        rec = db.get(FeedCache, (kind, h.lower()))
        if rec and rec.fetched_at:
            seen = rec.fetched_at
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if seen >= cutoff:
                fresh.add(h.lower())
    return fresh


def _mark_handles(db, kind, handles):
    now = _utcnow()
    for h in handles:
        key = h.lower()
        rec = db.get(FeedCache, (kind, key))
        if rec:
            rec.fetched_at = now
        else:
            db.add(FeedCache(kind=kind, handle=key, fetched_at=now))
    db.commit()


def overlay_fetch(db, profile, days, user_id):
    """Bluesky, Substack, extra RSS/GitHub for this user. Caps lists. No X.

    Public author feeds are cached globally by handle so N users sharing a
    Bluesky account do not mean N fetches in the same crawl window.
    """
    import sys
    import kerning_fetch as kf
    from app.crawl import upsert_rows

    people = ((profile or {}).get("seeds") or {}).get("people") or []
    resources = ((profile or {}).get("seeds") or {}).get("resources") or []
    people = people[: config.PEOPLE_CAP]
    resources = resources[: config.RESOURCE_CAP]
    capped = dict(profile or {})
    seeds = dict(capped.get("seeds") or {})
    seeds["people"] = people
    seeds["resources"] = resources
    capped["seeds"] = seeds

    bsky, subs, feeds, repos = [], [], {}, {}
    kf.apply_profile_follows(capped, [], bsky, subs)
    kf.apply_profile_resources(capped, feeds, repos, subs)

    bsky_fresh = _fresh_handles(db, "bsky", bsky)
    bsky_stale = [h for h in bsky if h.lower() not in bsky_fresh]
    if bsky_stale:
        try:
            got, _buzz = kf.fetch_bluesky(days, bsky_stale)
            upsert_rows(db, got, user_id=None)
            _mark_handles(db, "bsky", bsky_stale)
            print("overlay bluesky: %s" % len(got), file=sys.stderr)
        except Exception as e:
            print("overlay bluesky: failed (%s)" % e, file=sys.stderr)

    sub_fresh = _fresh_handles(db, "substack", subs)
    sub_stale = [h for h in subs if h.lower() not in sub_fresh]
    if sub_stale:
        try:
            got = kf.fetch_substack(days, sub_stale)
            upsert_rows(db, got, user_id=None)
            _mark_handles(db, "substack", sub_stale)
            print("overlay substack: %s" % len(got), file=sys.stderr)
        except Exception as e:
            print("overlay substack: failed (%s)" % e, file=sys.stderr)

    extra_feeds = {k: v for k, v in feeds.items() if v not in kf.CURATED_FEEDS.values()}
    extra_repos = {k: v for k, v in repos.items() if v not in kf.GITHUB_REPOS.values()}
    if extra_feeds:
        try:
            got = kf.fetch_feeds(days, extra_feeds)
            upsert_rows(db, got, user_id=user_id)
        except Exception as e:
            print("overlay feeds: failed (%s)" % e, file=sys.stderr)
    if extra_repos:
        try:
            got = kf.fetch_releases(days, extra_repos)
            upsert_rows(db, got, user_id=user_id)
        except Exception as e:
            print("overlay github: failed (%s)" % e, file=sys.stderr)


def run_cut(user_id, force=False):
    import time
    import kerning_fetch as kf
    from app.crawl import crawl_shared, pool_is_fresh, pool_items
    from kerning_lib.cut import cut_cadences

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return
        prof = db.get(Profile, user_id)
        profile = (prof.data if prof else {}) or {}
        now_dt = aware_now(user.timezone)
        existing = db.get(UserDigest, user_id)
        if existing and not force and cadences_current(existing.cadences or {}, now_dt):
            print("cut skip, digest current for %s" % user_id)
            return
        if not pool_is_fresh(db):
            db.close()
            crawl_shared()
            db = SessionLocal()
            user = db.get(User, user_id)
            if not user:
                return
            prof = db.get(Profile, user_id)
            profile = (prof.data if prof else {}) or {}
            now_dt = aware_now(user.timezone)
        month_start, _ = this_month(now_dt)
        days = max((time.time() - month_start.timestamp()) / 86400, 1 / 24)
        overlay_fetch(db, profile, days, user_id)
        rows = pool_items(db, user_id, since_ts=month_start.timestamp())
        items = kf.merge(rows)
        items = [i for i in items if i.get("title")]
        items = [
            i for i in items
            if i.get("always_relevant") or kf.lexicon_score(i["title"], i["url"]) >= 2
        ]
        skip = kf.downvoted_urls(profile)
        if skip:
            items = [i for i in items if i.get("key") not in skip]
        weights = profile.get("weights") or {}
        cadences = cut_cadences(items, weights, skip, now_dt, limit=12)
        rec = db.get(UserDigest, user_id)
        generated = datetime.now(timezone.utc).isoformat()
        if rec:
            rec.cadences = cadences
            rec.generated_at = generated
        else:
            db.add(UserDigest(user_id=user_id, cadences=cadences, generated_at=generated))
        db.commit()
        print("cut wrote digest for %s" % user_id)
    finally:
        db.close()


def run_job(job_id):
    from app.crawl import crawl_shared

    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        kind, user_id, force = job.kind, job.user_id, job.force
        if kind == "crawl":
            crawl_shared()
        elif kind == "cut" and user_id:
            run_cut(user_id, force=bool(force))
        rec = db.get(Job, job_id)
        if rec:
            rec.status = "done"
            rec.locked_at = None
            db.commit()
    except Exception as e:
        rec = db.get(Job, job_id)
        if rec:
            rec.status = "error"
            rec.error = str(e)
            rec.locked_at = None
            db.commit()
        raise
    finally:
        db.close()


def enqueue_nightly():
    db = SessionLocal()
    try:
        enqueue(db, "crawl", force_soon=True)
        for u in db.query(User).all():
            enqueue(db, "cut", u.id, delay_seconds=5, force_soon=True)
    finally:
        db.close()
