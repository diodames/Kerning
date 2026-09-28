import unittest
from datetime import datetime, timedelta, timezone

from kerning_lib.windows import (
    cadences_current,
    edition_meta,
    edition_week,
    expected_periods,
    last_week,
    payload_current,
    resolve_tz_name,
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

    def test_last_week_is_previous_monday_to_this_monday(self):
        now = datetime(2026, 9, 14, 17, 0, tzinfo=CEST)
        start, end = last_week(now)
        self.assertEqual(start.date().isoformat(), "2026-09-07")
        self.assertEqual(end.date().isoformat(), "2026-09-14")
        self.assertEqual(start.hour, 0)
        self.assertEqual(end.hour, 0)
        self.assertEqual(start.minute, 0)
        self.assertEqual(end.minute, 0)

    def test_expected_weekly_is_last_week_on_monday(self):
        now = datetime(2026, 9, 14, 17, 0, tzinfo=CEST)
        self.assertEqual(expected_periods(now)["weekly"], last_week(now))

    def test_expected_weekly_is_this_week_from_tuesday(self):
        now = datetime(2026, 9, 15, 17, 0, tzinfo=CEST)
        self.assertEqual(expected_periods(now)["weekly"], this_week(now))

    def test_edition_week_follows_viewer_zone(self):
        from zoneinfo import ZoneInfo

        utc = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
        prague = utc.astimezone(ZoneInfo("Europe/Prague"))
        ny = utc.astimezone(ZoneInfo("America/New_York"))
        self.assertEqual(prague.weekday(), 1)
        self.assertEqual(ny.weekday(), 0)
        self.assertEqual(edition_week(prague), this_week(prague))
        self.assertEqual(edition_week(ny), last_week(ny))

    def test_edition_week_flips_at_prague_midnight(self):
        from zoneinfo import ZoneInfo

        prague = ZoneInfo("Europe/Prague")
        monday = datetime(2026, 9, 14, 0, 0, tzinfo=prague)
        tuesday = datetime(2026, 9, 15, 0, 0, tzinfo=prague)
        self.assertEqual(edition_week(monday), last_week(monday))
        self.assertEqual(edition_week(tuesday), this_week(tuesday))

        still_monday = datetime(2026, 9, 13, 22, 0, tzinfo=timezone.utc).astimezone(prague)
        already_tuesday = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc).astimezone(prague)
        self.assertEqual(still_monday.date().isoformat(), "2026-09-14")
        self.assertEqual(already_tuesday.date().isoformat(), "2026-09-15")
        self.assertEqual(edition_week(still_monday), last_week(still_monday))
        self.assertEqual(edition_week(already_tuesday), this_week(already_tuesday))

    def test_resolve_tz_name_rejects_junk(self):
        self.assertEqual(resolve_tz_name("Europe/Prague"), "Europe/Prague")
        self.assertEqual(resolve_tz_name("UTC"), "UTC")
        self.assertIsNone(resolve_tz_name(""))
        self.assertIsNone(resolve_tz_name("not a zone"))
        self.assertIsNone(resolve_tz_name(None))

    def test_monday_this_week_pack_is_not_current(self):
        now = datetime(2026, 9, 14, 17, 0, tzinfo=CEST)
        packs = {}
        for kind, (start, end) in expected_periods(now).items():
            packs[kind] = edition_meta(kind, start, end)
        this_start, this_end = this_week(now)
        packs["weekly"] = edition_meta("weekly", this_start, this_end)
        self.assertEqual(packs["weekly"]["period_start"], "2026-09-14")
        self.assertFalse(cadences_current(packs, now))

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

    def test_payload_current_false_without_cadences(self):
        now = datetime(2026, 9, 7, 17, 0, tzinfo=CEST)
        self.assertFalse(payload_current(None, now))
        self.assertFalse(payload_current({}, now))

    def test_payload_current_true_for_matching_pack(self):
        now = datetime(2026, 9, 7, 17, 0, tzinfo=CEST)
        packs = {}
        for kind, (start, end) in expected_periods(now).items():
            packs[kind] = edition_meta(kind, start, end)
        self.assertTrue(payload_current({"cadences": packs}, now))

    def test_prague_dst_spring_forward_yesterday(self):
        from zoneinfo import ZoneInfo

        from kerning_lib.windows import close_cron_is_after_prague_midnight, to_prague

        prague = ZoneInfo("Europe/Prague")
        after = datetime(2026, 3, 30, 0, 30, tzinfo=prague)
        start, end = yesterday(after)
        self.assertEqual(start.date().isoformat(), "2026-03-29")
        self.assertEqual(end.date().isoformat(), "2026-03-30")
        self.assertEqual(start.utcoffset(), timedelta(hours=1))
        self.assertEqual(end.utcoffset(), timedelta(hours=2))
        self.assertEqual(end.timestamp() - start.timestamp(), 23 * 3600)
        winter_cron = datetime(2026, 1, 15, 23, 5, tzinfo=timezone.utc)
        summer_cron = datetime(2026, 7, 15, 23, 5, tzinfo=timezone.utc)
        early = datetime(2026, 1, 15, 22, 20, tzinfo=timezone.utc)
        self.assertTrue(close_cron_is_after_prague_midnight(winter_cron))
        self.assertTrue(close_cron_is_after_prague_midnight(summer_cron))
        self.assertFalse(close_cron_is_after_prague_midnight(early))
        self.assertEqual(to_prague(winter_cron).date().isoformat(), "2026-01-16")
        self.assertEqual(to_prague(summer_cron).date().isoformat(), "2026-07-16")

    def test_prague_dst_fall_back_yesterday(self):
        from zoneinfo import ZoneInfo

        from kerning_lib.windows import dates_in_period

        prague = ZoneInfo("Europe/Prague")
        monday = datetime(2026, 10, 26, 10, 0, tzinfo=prague)
        start, end = yesterday(monday)
        self.assertEqual(start.date().isoformat(), "2026-10-25")
        self.assertEqual(start.utcoffset(), timedelta(hours=2))
        self.assertEqual(end.utcoffset(), timedelta(hours=1))
        self.assertEqual(end.timestamp() - start.timestamp(), 25 * 3600)
        self.assertEqual(dates_in_period(start, end), ["2026-10-25"])



if __name__ == "__main__":
    unittest.main()
