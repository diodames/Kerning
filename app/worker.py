"""Claim queued crawl and cut jobs. Run: python3 -m app.worker"""

import time
from datetime import datetime

from app.db import SessionLocal, init_db
from app.jobs import claim_one, enqueue_nightly, recover_stuck, run_job


def loop(once=False):
    init_db()
    db = SessionLocal()
    try:
        recover_stuck(db, minutes=0)
    finally:
        db.close()
    last_nightly = None
    while True:
        now = datetime.now()
        today = now.date()
        if now.hour == 0 and now.minute >= 20 and last_nightly != today:
            enqueue_nightly()
            last_nightly = today
            print("enqueued nightly crawl and cuts", flush=True)
        payload = None
        db = SessionLocal()
        try:
            job = claim_one(db)
            if job:
                payload = (job.id, job.kind)
        finally:
            db.close()
        if payload:
            print("running %s %s" % (payload[1], payload[0]), flush=True)
            try:
                run_job(payload[0])
            except Exception as e:
                print("job failed: %s" % e, flush=True)
            if once:
                return
            continue
        if once:
            return
        time.sleep(2)


if __name__ == "__main__":
    import sys
    if "--nightly" in sys.argv:
        init_db()
        enqueue_nightly()
        print("enqueued nightly crawl and cuts", flush=True)
        sys.exit(0)
    loop(once="--once" in sys.argv)
