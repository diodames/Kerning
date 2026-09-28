import unittest
from datetime import datetime, timedelta, timezone

from kerning_fetch import canonical
from kerning_lib.pool import (
    empty_pool,
    items_for_prague_date,
    prune_pool,
    upsert_rows,
)


class CanonicalTests(unittest.TestCase):
    def test_strips_www_utm_slash_and_forces_https(self):
        self.assertEqual(
            canonical("http://www.example.com/post/?utm_source=x&ref=hn"),
            "https://example.com/post",
        )

    def test_youtu_be_becomes_youtube(self):
        self.assertEqual(
            canonical("https://youtu.be/abc"),
            "https://youtube.com/watch",
        )


class PoolUpsertTests(unittest.TestCase):
    def test_insert_then_update_keeps_first_seen_and_overwrites_score(self):
        now = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
        later = now + timedelta(hours=2)
        pool, inserted, updated = upsert_rows(empty_pool(), [{
            "url": "https://www.example.com/a?utm_campaign=1",
            "title": "First",
            "source": "Hacker News",
            "points": 3,
            "comments": 1,
            "ts": now.timestamp(),
        }], now=now)
        self.assertEqual(inserted, 1)
        self.assertEqual(updated, 0)
        key = canonical("https://example.com/a")
        first_seen = pool["items"][key]["first_seen"]
        pool, inserted, updated = upsert_rows(pool, [{
            "url": "https://example.com/a/",
            "title": "First",
            "source": "Hacker News",
            "points": 180,
            "comments": 40,
            "ts": now.timestamp(),
        }], now=later)
        self.assertEqual(inserted, 0)
        self.assertEqual(updated, 1)
        item = pool["items"][key]
        self.assertEqual(item["first_seen"], first_seen)
        self.assertEqual(item["points"], 180)
        self.assertEqual(item["comments"], 40)
        self.assertEqual(len(pool["items"]), 1)

    def test_items_for_prague_date_use_first_seen(self):
        from zoneinfo import ZoneInfo

        prague = ZoneInfo("Europe/Prague")
        first = datetime(2026, 9, 20, 23, 30, tzinfo=prague)
        pool, _, _ = upsert_rows(empty_pool(), [{
            "url": "https://example.com/a",
            "title": "A",
            "source": "Hacker News",
            "points": 12,
            "ts": first.timestamp(),
        }], now=first)
        found = items_for_prague_date(pool, "2026-09-20")
        self.assertEqual(len(found), 1)
        self.assertEqual(items_for_prague_date(pool, "2026-09-21"), [])

    def test_prune_drops_old_last_seen(self):
        now = datetime(2026, 9, 21, tzinfo=timezone.utc)
        old = now - timedelta(days=61)
        pool, _, _ = upsert_rows(empty_pool(), [{
            "url": "https://example.com/old",
            "title": "Old",
            "source": "Hacker News",
            "points": 10,
            "ts": old.timestamp(),
        }], now=old)
        pool, dropped = prune_pool(pool, now=now, days=60)
        self.assertEqual(dropped, 1)
        self.assertEqual(pool["items"], {})
