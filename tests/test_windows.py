import unittest
from datetime import datetime, timedelta, timezone

from kerning_lib.windows import (
    cadences_current,
    edition_meta,
    expected_periods,
    this_month,
    this_week,
    yesterday,
)


CEST = timezone(timedelta(hours=2))


class WindowsTests(unittest.TestCase):
    def test_monday_yesterday_is_sunday(self):
        now = datetime(2026, 9, 7, 17, 0, tzinfo=CEST)
        start, end = yesterday(now)
        self.assertEqual(start.date().isoformat(), "2026-09-06")
        self.assertEqual(end.date().isoformat(), "2026-09-07")

    def test_week_is_monday_to_monday(self):
        now = datetime(2026, 9, 7, 12, 0, tzinfo=CEST)
        start, end = this_week(now)
        self.assertEqual(start.date().isoformat(), "2026-09-07")
        self.assertEqual(end.date().isoformat(), "2026-09-14")

    def test_month_is_calendar_month(self):
        now = datetime(2026, 9, 7, 12, 0, tzinfo=CEST)
        start, end = this_month(now)
        self.assertEqual(start.date().isoformat(), "2026-09-01")
        self.assertEqual(end.date().isoformat(), "2026-10-01")

    def test_cadences_current_true_for_matching_pack(self):
        now = datetime(2026, 9, 7, 17, 0, tzinfo=CEST)
        packs = {}
        for kind, (start, end) in expected_periods(now).items():
            packs[kind] = edition_meta(kind, start, end)
        self.assertTrue(cadences_current(packs, now))

    def test_cadences_current_false_when_daily_is_old(self):
        now = datetime(2026, 9, 7, 17, 0, tzinfo=CEST)
        packs = {}
        for kind, (start, end) in expected_periods(now).items():
            packs[kind] = edition_meta(kind, start, end)
        packs["daily"]["period_start"] = "2026-09-05"
        packs["daily"]["period_end"] = "2026-09-05"
        self.assertFalse(cadences_current(packs, now))


if __name__ == "__main__":
    unittest.main()
