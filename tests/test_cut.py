import unittest
from datetime import datetime, timedelta, timezone

from kerning_lib.cut import cut_cadences


CEST = timezone(timedelta(hours=2))


def _item(url, title, ts, points=10):
    return {
        "key": url,
        "title": title,
        "url": url,
        "discussion": url,
        "sources": ["Hacker News"],
        "points": points,
        "comments": 0,
        "ts": ts,
        "curated": False,
        "always_relevant": True,
        "authors": [],
        "sharers": 0,
        "share_engagement": 0,
        "_buzz": (0, 0),
    }


class CutTests(unittest.TestCase):
    def test_daily_keeps_yesterday_not_today(self):
        now = datetime(2026, 9, 7, 17, 0, tzinfo=CEST)
        sunday = datetime(2026, 9, 6, 12, 0, tzinfo=CEST).timestamp()
        monday = datetime(2026, 9, 7, 10, 0, tzinfo=CEST).timestamp()
        items = [
            _item("https://example.com/sun", "Sunday design system", sunday, 20),
            _item("https://example.com/mon", "Monday only post", monday, 99),
        ]
        packs = cut_cadences(items, {}, set(), now, limit=12)
        urls = [it["url"] for it in packs["daily"]["items"]]
        self.assertIn("https://example.com/sun", urls)
        self.assertNotIn("https://example.com/mon", urls)
        self.assertEqual(packs["daily"]["period_start"], "2026-09-06")

    def test_weekly_includes_monday_of_this_week(self):
        now = datetime(2026, 9, 7, 17, 0, tzinfo=CEST)
        monday = datetime(2026, 9, 7, 10, 0, tzinfo=CEST).timestamp()
        last_sun = datetime(2026, 9, 6, 10, 0, tzinfo=CEST).timestamp()
        items = [
            _item("https://example.com/mon", "This week", monday, 20),
            _item("https://example.com/old", "Last week leftover", last_sun, 20),
        ]
        packs = cut_cadences(items, {}, set(), now, limit=12)
        urls = [it["url"] for it in packs["weekly"]["items"]]
        self.assertIn("https://example.com/mon", urls)
        self.assertNotIn("https://example.com/old", urls)


if __name__ == "__main__":
    unittest.main()
