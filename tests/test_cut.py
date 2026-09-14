import unittest
from datetime import datetime, timedelta, timezone

from kerning_lib.cut import apply_kept_weekly, cut_cadences, keep_previous_weekly


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

    def test_weekly_is_last_complete_week_on_monday(self):
        now = datetime(2026, 9, 14, 17, 0, tzinfo=CEST)
        last_sun = datetime(2026, 9, 13, 10, 0, tzinfo=CEST).timestamp()
        this_mon = datetime(2026, 9, 14, 10, 0, tzinfo=CEST).timestamp()
        items = [
            _item("https://example.com/sun", "Last Sunday leftover", last_sun, 20),
            _item("https://example.com/mon", "This Monday", this_mon, 99),
        ]
        packs = cut_cadences(items, {}, set(), now, limit=12)
        urls = [it["url"] for it in packs["weekly"]["items"]]
        self.assertIn("https://example.com/sun", urls)
        self.assertNotIn("https://example.com/mon", urls)
        self.assertEqual(packs["weekly"]["period_start"], "2026-09-07")

    def test_weekly_is_this_week_from_tuesday(self):
        now = datetime(2026, 9, 15, 17, 0, tzinfo=CEST)
        last_sun = datetime(2026, 9, 13, 10, 0, tzinfo=CEST).timestamp()
        this_mon = datetime(2026, 9, 14, 10, 0, tzinfo=CEST).timestamp()
        items = [
            _item("https://example.com/sun", "Last Sunday leftover", last_sun, 20),
            _item("https://example.com/mon", "This Monday", this_mon, 99),
        ]
        packs = cut_cadences(items, {}, set(), now, limit=12)
        urls = [it["url"] for it in packs["weekly"]["items"]]
        self.assertIn("https://example.com/mon", urls)
        self.assertNotIn("https://example.com/sun", urls)
        self.assertEqual(packs["weekly"]["period_start"], "2026-09-14")

    def test_empty_weekly_keeps_previous_pack(self):
        previous = {
            "cadences": {
                "weekly": {
                    "period_start": "2026-09-07",
                    "period_end": "2026-09-13",
                    "week_start": "2026-09-07",
                    "items": [{"url": "https://example.com/kept"}],
                }
            }
        }
        cadences = {
            "daily": {"items": []},
            "weekly": {
                "period_start": "2026-09-14",
                "period_end": "2026-09-20",
                "items": [],
            },
        }
        kept = keep_previous_weekly(cadences, previous)
        self.assertEqual(kept["weekly"]["items"][0]["url"], "https://example.com/kept")
        self.assertEqual(kept["weekly"]["period_start"], "2026-09-07")

        payload = apply_kept_weekly(
            {"cadences": cadences, "items": [], "week_start": "2026-09-14"},
            previous,
        )
        self.assertEqual(payload["items"][0]["url"], "https://example.com/kept")
        self.assertEqual(payload["week_start"], "2026-09-07")

    def test_empty_weekly_stays_empty_without_previous_items(self):
        cadences = {"weekly": {"items": []}}
        kept = keep_previous_weekly(cadences, {"cadences": {"weekly": {"items": []}}})
        self.assertEqual(kept["weekly"]["items"], [])
        self.assertIs(keep_previous_weekly(cadences, None), cadences)


if __name__ == "__main__":
    unittest.main()
