import os
import unittest
from datetime import datetime, timedelta, timezone

from kerning_lib.blob_digest import blob_url, lock_is_fresh, should_skip_fetch, store_id
from kerning_lib.windows import aware_now, edition_meta, expected_periods, resolve_tz_name, this_week


CEST = timezone(timedelta(hours=2))


def _pack(now):
    packs = {}
    for kind, (start, end) in expected_periods(now).items():
        packs[kind] = edition_meta(kind, start, end)
    return {"cadences": packs}


class BlobUrlTests(unittest.TestCase):
    def test_url_from_store_id(self):
        env = {"BLOB_STORE_ID": "store_y3OzWQB7nsWLkNEv"}
        self.assertEqual(
            blob_url("kerning/digest.json", env),
            "https://y3ozwqb7nswlknev.private.blob.vercel-storage.com/kerning/digest.json",
        )

    def test_store_id_falls_back_to_token(self):
        env = {"BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_Y3OzWQB7nsWLkNEv_secretpart"}
        self.assertEqual(store_id(env), "y3ozwqb7nswlknev")
        self.assertEqual(store_id({}), "")
        with self.assertRaises(RuntimeError):
            blob_url("kerning/pool.json", {})


class DataDirTests(unittest.TestCase):
    def test_data_dir_wins_over_blob_token(self):
        import tempfile
        from unittest import mock

        from kerning_lib import store

        with tempfile.TemporaryDirectory() as root:
            env = {"KERNING_DATA_DIR": root, "BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_x_y"}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(store, "_put_json") as blob_put:
                store.put_json(store.POOL_PATH, {"items": []})
                store.put_json("kerning/digest.json", {"cadences": {}})
                store.put_json(store.day_path("2026-10-08"), {"items": []})
                self.assertEqual(store.get_json(store.POOL_PATH), {"items": []})
            blob_put.assert_not_called()
            self.assertTrue(os.path.isfile(os.path.join(root, "pool.json")))
            self.assertTrue(os.path.isfile(os.path.join(root, "digest.json")))
            self.assertTrue(os.path.isfile(os.path.join(root, "days", "2026-10-08.json")))


class BlobDigestTests(unittest.TestCase):
    def test_skip_fetch_when_windows_match(self):
        now = datetime(2026, 9, 8, 9, 0, tzinfo=CEST)
        data = _pack(now)
        self.assertTrue(should_skip_fetch(data, force=False, now=now))
        self.assertFalse(should_skip_fetch(data, force=True, now=now))

    def test_skip_fetch_when_last_complete_week_matches_prague(self):
        from zoneinfo import ZoneInfo

        now = datetime(2026, 9, 14, 17, 0, tzinfo=ZoneInfo("Europe/Prague"))
        data = _pack(now)
        weekly = data["cadences"]["weekly"]
        self.assertEqual(weekly["period_start"], "2026-09-07")
        self.assertEqual(weekly["period_end"], "2026-09-13")
        self.assertTrue(should_skip_fetch(data, force=False, now=now))

    def test_monday_does_not_skip_empty_this_week_pack(self):
        now = datetime(2026, 9, 14, 17, 0, tzinfo=CEST)
        data = _pack(now)
        this_start, this_end = this_week(now)
        data["cadences"]["weekly"] = edition_meta("weekly", this_start, this_end)
        data["cadences"]["weekly"]["items"] = []
        self.assertEqual(data["cadences"]["weekly"]["period_start"], "2026-09-14")
        self.assertFalse(should_skip_fetch(data, force=False, now=now))

    def test_skip_fetch_when_this_week_matches_prague_from_tuesday(self):
        from zoneinfo import ZoneInfo

        now = datetime(2026, 9, 15, 17, 0, tzinfo=ZoneInfo("Europe/Prague"))
        data = _pack(now)
        weekly = data["cadences"]["weekly"]
        self.assertEqual(weekly["period_start"], "2026-09-14")
        self.assertEqual(weekly["period_end"], "2026-09-20")
        self.assertTrue(should_skip_fetch(data, force=False, now=now))

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

    def test_skip_fetch_follows_posted_zone_at_prague_tuesday_ny_monday(self):
        from zoneinfo import ZoneInfo

        utc = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
        prague = utc.astimezone(ZoneInfo("Europe/Prague"))
        ny = utc.astimezone(ZoneInfo("America/New_York"))
        prague_pack = _pack(prague)
        self.assertEqual(prague.weekday(), 1)
        self.assertEqual(ny.weekday(), 0)
        self.assertEqual(prague_pack["cadences"]["weekly"]["period_start"], "2026-09-14")
        self.assertEqual(prague_pack["cadences"]["weekly"]["period_end"], "2026-09-20")
        self.assertTrue(should_skip_fetch(prague_pack, now=prague))
        self.assertFalse(should_skip_fetch(prague_pack, now=ny))

    def test_junk_timezone_is_ignored_like_rebuild(self):
        tz_name = resolve_tz_name("not a zone")
        self.assertIsNone(tz_name)
        now = aware_now(tz_name) if tz_name else None
        self.assertIsNone(now)
        data = _pack(datetime(2026, 9, 14, 17, 0, tzinfo=CEST))
        self.assertTrue(should_skip_fetch(data, force=False, now=datetime(2026, 9, 14, 17, 0, tzinfo=CEST)))


if __name__ == "__main__":
    unittest.main()
