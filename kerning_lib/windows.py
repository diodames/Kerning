"""Calendar windows for Daily, Weekly, and Monthly editions."""

import json
import os
from datetime import datetime, timedelta

RECENCY_TAU = {"daily": 1.5, "weekly": 21, "monthly": 45}


def aware_now(tz_name=None):
    """Timezone-aware now. tz_name is an IANA zone, e.g. Europe/Prague."""
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now().astimezone()


def this_week(now=None):
    """Monday 00:00 local through next Monday 00:00."""
    now = now or aware_now()
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


def this_day(now=None):
    now = now or aware_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def yesterday(now=None):
    """Yesterday 00:00 local through today 00:00 — the last complete calendar day."""
    today, _ = this_day(now)
    return today - timedelta(days=1), today


def this_month(now=None):
    now = now or aware_now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def week_label(start, end):
    last = end - timedelta(seconds=1)
    if start.month == last.month and start.year == last.year:
        return f"{start.day}–{last.day} {start.strftime('%B %Y')}"
    if start.year == last.year:
        return f"{start.day} {start.strftime('%B')} – {last.day} {last.strftime('%B %Y')}"
    return (
        f"{start.day} {start.strftime('%B %Y')} – "
        f"{last.day} {last.strftime('%B %Y')}"
    )


def iso_week_id(start):
    iso = start.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def edition_meta(kind, start, end):
    last = end - timedelta(seconds=1)
    meta = {
        "label": {
            "daily": f"{start.day} {start.strftime('%B %Y')}",
            "weekly": week_label(start, end),
            "monthly": start.strftime("%B %Y"),
        }[kind],
        "period_start": start.date().isoformat(),
        "period_end": last.date().isoformat(),
    }
    if kind == "weekly":
        meta["week_start"] = meta["period_start"]
        meta["week_end"] = meta["period_end"]
        meta["week_label"] = meta["label"]
        meta["iso_week"] = iso_week_id(start)
    return meta


def expected_periods(now=None):
    now = now or aware_now()
    return {
        "daily": yesterday(now),
        "weekly": this_week(now),
        "monthly": this_month(now),
    }


def cadences_current(cadences, now=None):
    """True when cadence packs cover yesterday, this week, and this month."""
    packs = cadences or {}
    now = now or aware_now()
    for kind, (start, end) in expected_periods(now).items():
        pack = packs.get(kind) or {}
        meta = edition_meta(kind, start, end)
        if pack.get("period_start") != meta["period_start"]:
            return False
        if pack.get("period_end") != meta["period_end"]:
            return False
    return True


def digest_current(path, now=None):
    """True when a digest.json file already covers the three windows."""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return cadences_current(data.get("cadences") or {}, now)
