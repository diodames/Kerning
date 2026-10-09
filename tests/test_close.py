import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from kerning_lib.close import close_day, compose_from_days, run_close
from kerning_lib.windows import edition_week, this_month
from zoneinfo import ZoneInfo


PRAGUE = ZoneInfo("Europe/Prague")


def _day_item(url, score=2.0):
    return {
        "url": url,
        "title": url,
        "sources": ["Hacker News"],
        "points": 20,
        "comments": 4,
        "score": score,
    }


class ComposeFromDaysTests(unittest.TestCase):
    def test_weekly_and_monthly_do_not_read_pool(self):
        now = datetime(2026, 9, 16, 10, 0, tzinfo=PRAGUE)
        week_start, week_end = edition_week(now)
        month_start, month_end = this_month(now)
        days = {
            "2026-09-15": {"items": [_day_item("https://a.example/p", 5)]},
            "2026-09-14": {"items": [_day_item("https://b.example/q", 4)]},
        }
        with patch("kerning_lib.close.get_json", side_effect=AssertionError("no store reads")):
            payload = compose_from_days(days, now=now, previous=None)
        weekly_urls = [it["url"] for it in payload["cadences"]["weekly"]["items"]]
        self.assertIn("https://a.example/p", weekly_urls)
        self.assertEqual(payload["cadences"]["weekly"]["period_start"], week_start.date().isoformat())
        self.assertEqual(payload["cadences"]["monthly"]["period_start"], month_start.date().isoformat())
        self.assertEqual(week_end.date().isoformat(), "2026-09-21")
        self.assertEqual(month_end.date().isoformat(), "2026-10-01")


class CloseDayTests(unittest.TestCase):
    def test_quality_and_lexicon_reasons_land_in_stats(self):
        pool = {"items": {
            "https://spam.example/x": {
                "url": "https://spam.example/x",
                "title": "Spam",
                "sources": ["Hacker News"],
                "points": 99,
                "comments": 9,
                "first_seen": "2026-09-20T08:00:00+00:00",
                "ts": 0,
            },
            "https://example.com/keep": {
                "url": "https://example.com/keep",
                "title": "zzz",
                "sources": ["Hacker News"],
                "points": 40,
                "comments": 8,
                "first_seen": "2026-09-20T08:00:00+00:00",
                "always_relevant": True,
                "ts": 0,
            },
        }}
        cfg = {
            "hn": {"min_points": 10, "min_comments": 5},
            "lobsters": {"min_score": 3},
            "blocklist": ["spam.example"],
            "allowlist": [],
            "saas_domains": {},
        }
        payload, stats = close_day("2026-09-20", pool, cfg)
        self.assertEqual(payload["date"], "2026-09-20")
        self.assertEqual(stats["pool"], 2)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["dropped"].get("blocklist"), 1)
        self.assertEqual(payload["items"][0]["url"], "https://example.com/keep")


CFG = {
    "hn": {"min_points": 10, "min_comments": 5},
    "lobsters": {"min_score": 3},
    "blocklist": [],
    "allowlist": [],
    "saas_domains": {},
}


def _pool_item(url, published, first_seen):
    return {
        "key": url,
        "url": url,
        "title": "Design system " + url,
        "sources": ["Hacker News"],
        "points": 40,
        "comments": 8,
        "ts": published.timestamp(),
        "first_seen": first_seen.astimezone(timezone.utc).isoformat(),
        "always_relevant": True,
    }


class FakeStore:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.puts = []
        self.gets = []

    def get(self, path):
        self.gets.append(path)
        return self.files.get(path)

    def put(self, path, data):
        self.puts.append(path)
        self.files[path] = data

    def patches(self):
        return [
            patch("kerning_lib.close.get_json", side_effect=self.get),
            patch("kerning_lib.close.put_json", side_effect=self.put),
            patch("kerning_lib.close.load_quality", return_value=CFG),
        ]


def _run(store, **kwargs):
    ps = store.patches()
    for p in ps:
        p.start()
    try:
        return run_close(**kwargs)
    finally:
        for p in ps:
            p.stop()


class BackfillTests(unittest.TestCase):
    def test_fresh_pool_fills_daily_weekly_monthly(self):
        now = datetime(2026, 9, 29, 0, 5, tzinfo=PRAGUE)
        seen = datetime(2026, 9, 28, 12, 0, tzinfo=PRAGUE)
        items = {}
        for i, day in enumerate((22, 24, 26, 27, 28)):
            url = "https://s%d.example/p" % day
            items[url] = _pool_item(url, datetime(2026, 9, day, 9, 0, tzinfo=PRAGUE), seen)
            items[url]["sources"] = [("Hacker News", "Publications")[i % 2]]
        store = FakeStore({"kerning/pool.json": {"items": items}})
        result = _run(store, now=now)
        self.assertTrue(result["closed"])
        self.assertEqual(result["date"], "2026-09-28")
        self.assertEqual(result["backfilled"], ["2026-09-22", "2026-09-24",
                                                "2026-09-26", "2026-09-27"])
        day27 = store.files["kerning/days/2026-09-27.json"]
        self.assertTrue(day27["backfill"])
        self.assertEqual([it["url"] for it in day27["items"]], ["https://s27.example/p"])
        day28 = [it["url"] for it in store.files["kerning/days/2026-09-28.json"]["items"]]
        self.assertEqual(day28, ["https://s28.example/p"])
        self.assertNotIn("backfill", store.files["kerning/days/2026-09-28.json"])
        self.assertNotIn("kerning/days/2026-09-23.json", store.files)
        cad = store.files["kerning/digest.json"]["cadences"]
        self.assertEqual(len(cad["daily"]["items"]), 1)
        self.assertEqual(len(cad["weekly"]["items"]), 1)
        self.assertEqual(len(cad["monthly"]["items"]), 5)

    def test_backfill_never_touches_existing_days_or_repeats_urls(self):
        now = datetime(2026, 9, 29, 0, 5, tzinfo=PRAGUE)
        seen = datetime(2026, 9, 28, 12, 0, tzinfo=PRAGUE)
        url = "https://dup.example/p"
        items = {
            url: _pool_item(url, datetime(2026, 9, 27, 9, 0, tzinfo=PRAGUE), seen),
            "https://new.example/p": _pool_item(
                "https://new.example/p", datetime(2026, 9, 26, 9, 0, tzinfo=PRAGUE), seen),
        }
        kept_day = {"date": "2026-09-25", "items": [{"url": url, "score": 3}]}
        store = FakeStore({
            "kerning/pool.json": {"items": items},
            "kerning/days/2026-09-25.json": kept_day,
        })
        result = _run(store, now=now)
        self.assertEqual(result["backfilled"], ["2026-09-26"])
        self.assertIs(store.files["kerning/days/2026-09-25.json"], kept_day)
        self.assertNotIn("kerning/days/2026-09-27.json", store.files)
        self.assertEqual(store.files["kerning/days/2026-09-28.json"]["items"], [])


class PrePoolDayTests(unittest.TestCase):
    def test_day_before_pool_started_is_not_closed_empty(self):
        now = datetime(2026, 9, 28, 11, 0, tzinfo=PRAGUE)
        seen = datetime(2026, 9, 28, 10, 0, tzinfo=PRAGUE)
        url = "https://sun.example/p"
        store = FakeStore({"kerning/pool.json": {"items": {
            url: _pool_item(url, datetime(2026, 9, 27, 9, 0, tzinfo=PRAGUE), seen),
        }}})
        result = _run(store, now=now)
        self.assertEqual(result["date"], "2026-09-27")
        self.assertEqual(result["kept"], 1)
        self.assertEqual(store.files["kerning/days/2026-09-27.json"]["items"][0]["url"], url)


class BlobBudgetTests(unittest.TestCase):
    def _fresh(self):
        seen = datetime(2026, 9, 28, 12, 0, tzinfo=PRAGUE)
        url = "https://s28.example/p"
        return FakeStore({"kerning/pool.json": {"items": {
            url: _pool_item(url, datetime(2026, 9, 28, 9, 0, tzinfo=PRAGUE), seen),
        }}})

    def test_close_writes_day_stats_index_digest_once(self):
        store = self._fresh()
        _run(store, now=datetime(2026, 9, 29, 0, 5, tzinfo=PRAGUE))
        self.assertEqual(sorted(store.puts), sorted([
            "kerning/days/2026-09-28.json",
            "kerning/days/2026-09-28.stats.json",
            "kerning/days/index.json",
            "kerning/digest.json",
        ]))

    def test_after_migration_close_reads_no_day_files(self):
        store = self._fresh()
        _run(store, now=datetime(2026, 9, 29, 0, 5, tzinfo=PRAGUE))
        store.gets.clear()
        _run(store, now=datetime(2026, 9, 30, 0, 5, tzinfo=PRAGUE))
        self.assertEqual(sorted(store.gets), [
            "kerning/days/index.json", "kerning/digest.json", "kerning/pool.json",
        ])

    def test_repeat_close_writes_nothing_and_skips_pool(self):
        store = self._fresh()
        _run(store, now=datetime(2026, 9, 29, 0, 5, tzinfo=PRAGUE))
        store.puts.clear()
        store.gets.clear()
        result = _run(store, now=datetime(2026, 9, 29, 0, 15, tzinfo=PRAGUE))
        self.assertFalse(result["closed"])
        self.assertEqual(result["kept"], 1)
        self.assertEqual(store.puts, [])
        self.assertEqual(sorted(store.gets), ["kerning/days/index.json", "kerning/digest.json"])

    def test_existing_day_files_migrate_into_index(self):
        existing = {"date": "2026-09-20", "items": [_day_item("https://a.example/x")]}
        store = FakeStore({
            "kerning/days/2026-09-20.json": existing,
            "kerning/days/2026-09-20.stats.json": {"pool": 9, "kept": 1,
                                                   "dropped": {"lexicon": 2}},
        })
        result = _run(store, date="2026-09-20",
                      now=datetime(2026, 9, 21, 0, 5, tzinfo=PRAGUE))
        self.assertFalse(result["closed"])
        self.assertEqual(result["dropped"], {"lexicon": 2})
        self.assertNotIn("kerning/days/2026-09-20.json", store.puts)
        index = store.files["kerning/days/index.json"]["days"]
        self.assertEqual(index["2026-09-20"]["items"][0]["url"], "https://a.example/x")

    def test_force_rewrites_a_closed_day(self):
        store = self._fresh()
        _run(store, now=datetime(2026, 9, 29, 0, 5, tzinfo=PRAGUE))
        store.puts.clear()
        result = _run(store, date="2026-09-28", force=True,
                      now=datetime(2026, 9, 29, 9, 0, tzinfo=PRAGUE))
        self.assertTrue(result["closed"])
        self.assertEqual(result["kept"], 1)
        self.assertIn("kerning/days/2026-09-28.json", store.puts)


class DailyFallbackTests(unittest.TestCase):
    def test_empty_yesterday_uses_latest_closed_day_with_its_dates(self):
        now = datetime(2026, 9, 16, 10, 0, tzinfo=PRAGUE)
        days = {
            "2026-09-15": {"items": []},
            "2026-09-13": {"items": [_day_item("https://a.example/p")]},
        }
        payload = compose_from_days(days, now=now, previous=None)
        daily = payload["cadences"]["daily"]
        self.assertEqual(daily["items"][0]["url"], "https://a.example/p")
        self.assertEqual(daily["period_start"], "2026-09-13")
        self.assertEqual(daily["period_end"], "2026-09-13")

    def test_no_closed_day_in_a_week_keeps_previous_daily(self):
        now = datetime(2026, 9, 16, 10, 0, tzinfo=PRAGUE)
        previous = {"cadences": {"daily": {"period_start": "2026-09-01",
                                           "items": [_day_item("https://old.example/p")]}}}
        payload = compose_from_days({}, now=now, previous=previous)
        self.assertEqual(payload["cadences"]["daily"]["items"][0]["url"], "https://old.example/p")


class CandidateTests(unittest.TestCase):
    def test_day_keeps_wider_candidates_around_its_picks(self):
        published = datetime(2026, 9, 20, 9, 0, tzinfo=PRAGUE)
        items = {}
        for i in range(40):
            url = "https://s%d.example/p" % i
            items[url] = _pool_item(url, published, published)
            items[url]["sources"] = ["Source %d" % i]
            items[url]["points"] = 20 + i
        payload, _ = close_day("2026-09-20", {"items": items}, CFG)
        cand = [it["url"] for it in payload["candidates"]]
        self.assertEqual(len(payload["items"]), 4)
        self.assertEqual(len(cand), 30)
        self.assertTrue({it["url"] for it in payload["items"]} <= set(cand))
        scores = [it["score"] for it in payload["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_editions_carry_candidates_with_limits(self):
        now = datetime(2026, 9, 16, 10, 0, tzinfo=PRAGUE)
        days = {}
        for d in range(1, 16):
            date = "2026-09-%02d" % d
            cands = [_day_item("https://d%d-%d.example/p" % (d, i), score=i) for i in range(30)]
            days[date] = {"items": cands[-4:], "candidates": cands}
        cad = compose_from_days(days, now=now, previous=None)["cadences"]
        self.assertEqual(len(cad["daily"]["candidates"]), 30)
        self.assertEqual(len(cad["weekly"]["candidates"]), 60)
        self.assertEqual(len(cad["monthly"]["candidates"]), 100)
        for kind in ("daily", "weekly", "monthly"):
            urls = {it["url"] for it in cad[kind]["candidates"]}
            self.assertTrue({it["url"] for it in cad[kind]["items"]} <= urls, kind)

    def test_days_without_candidates_fall_back_to_items(self):
        now = datetime(2026, 9, 16, 10, 0, tzinfo=PRAGUE)
        days = {"2026-09-15": {"items": [_day_item("https://a.example/p")]}}
        cad = compose_from_days(days, now=now, previous=None)["cadences"]
        self.assertEqual([it["url"] for it in cad["daily"]["candidates"]], ["https://a.example/p"])
        self.assertEqual([it["url"] for it in cad["weekly"]["candidates"]], ["https://a.example/p"])
