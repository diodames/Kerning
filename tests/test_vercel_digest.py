import os
import unittest
from datetime import datetime, timedelta, timezone

from kerning_lib.blob_digest import lock_is_fresh, should_skip_fetch
from kerning_lib.windows import edition_meta, expected_periods


CEST = timezone(timedelta(hours=2))


def _pack(now):
    packs = {}
    for kind, (start, end) in expected_periods(now).items():
        packs[kind] = edition_meta(kind, start, end)
    return {"cadences": packs}


class BlobDigestTests(unittest.TestCase):
    def test_skip_fetch_when_windows_match(self):
        now = datetime(2026, 9, 8, 9, 0, tzinfo=CEST)
        data = _pack(now)
        self.assertTrue(should_skip_fetch(data, force=False, now=now))
        self.assertFalse(should_skip_fetch(data, force=True, now=now))

    def test_do_not_skip_missing_or_stale(self):
        now = datetime(2026, 9, 8, 9, 0, tzinfo=CEST)
        self.assertFalse(should_skip_fetch(None, now=now))
        self.assertFalse(should_skip_fetch({}, now=now))
        stale = _pack(now)
        stale["cadences"]["daily"]["period_start"] = "2026-09-06"
        stale["cadences"]["daily"]["period_end"] = "2026-09-06"
        self.assertFalse(should_skip_fetch(stale, force=False, now=now))

    def test_lock_is_fresh_within_ttl(self):
        now = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
        self.assertFalse(lock_is_fresh(None, now=now))
        self.assertTrue(lock_is_fresh({"started_at": now.isoformat()}, now=now))
        old = now - timedelta(seconds=241)
        self.assertFalse(lock_is_fresh({"started_at": old.isoformat()}, now=now))

    def test_aware_now_respects_digest_tz(self):
        from kerning_lib.windows import aware_now
        previous = os.environ.get("DIGEST_TZ")
        os.environ["DIGEST_TZ"] = "Europe/Prague"
        try:
            now = aware_now()
            self.assertEqual(getattr(now.tzinfo, "key", None), "Europe/Prague")
        finally:
            if previous is None:
                os.environ.pop("DIGEST_TZ", None)
            else:
                os.environ["DIGEST_TZ"] = previous

    def test_utc_host_after_prague_midnight_still_needs_yesterdays_cut(self):
        """Vercel is UTC. At 23:05 UTC on 8 Sep it is already 9 Sep in Prague.

        The skip check follows DIGEST_TZ (yesterday = 8 Sep). The cut used to
        follow the host clock (yesterday = 7 Sep) and rewrote a stale Daily.
        """
        from zoneinfo import ZoneInfo

        from kerning_lib.windows import yesterday

        utc = datetime(2026, 9, 8, 23, 5, tzinfo=timezone.utc)
        prague = utc.astimezone(ZoneInfo("Europe/Prague"))
        utc_yday, _ = yesterday(utc)
        prague_yday, _ = yesterday(prague)
        self.assertEqual(prague.date().isoformat(), "2026-09-09")
        self.assertEqual(utc_yday.date().isoformat(), "2026-09-07")
        self.assertEqual(prague_yday.date().isoformat(), "2026-09-08")

        host_pack = _pack(utc)
        self.assertEqual(host_pack["cadences"]["daily"]["period_start"], "2026-09-07")
        self.assertTrue(should_skip_fetch(host_pack, now=utc))
        self.assertFalse(should_skip_fetch(host_pack, now=prague))
        self.assertEqual(
            _pack(prague)["cadences"]["daily"]["period_start"], "2026-09-08"
        )


if __name__ == "__main__":
    unittest.main()
