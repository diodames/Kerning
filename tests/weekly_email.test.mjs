import test from "node:test";
import assert from "node:assert/strict";
import {
  readerDue, SLOT_HOURS, lastClosedDates, packFromDays, weekLabel, isoWeekId,
  render, WEEKLY_LIMIT,
} from "../scripts/weekly_email.mjs";

const ISO = "2026-W46";
const mondayMorningPrague = new Date("2026-11-09T07:00:00Z"); // 08:00 Europe/Prague (CET)
const mondayEarlyPrague = new Date("2026-11-09T06:30:00Z"); // 07:30 Prague, before 08:00
const tuesdayMorningPrague = new Date("2026-11-10T07:00:00Z"); // 08:00 Prague Tuesday
const thursdayAfternoonPrague = new Date("2026-11-12T12:00:00Z"); // 13:00 Prague Thursday
const fridayEveningPrague = new Date("2026-11-13T17:00:00Z"); // 18:00 Prague
const fridayAfternoonPrague = new Date("2026-11-13T16:30:00Z"); // 17:30 Prague
const saturdayPrague = new Date("2026-11-14T09:00:00Z"); // 10:00 Prague Saturday

function pref(extra) {
  return Object.assign({
    weekly: true,
    send_dow: 1,
    send_slot: "morning",
    timezone: "Europe/Prague",
    last_sent_week: null,
  }, extra || {});
}

function dayItem(n, extra) {
  return Object.assign({
    id: "item-" + n,
    title: "Story " + n,
    url: "https://example.com/s" + n,
    score: 20 - n,
    sources: ["hn"],
  }, extra || {});
}

test("slot hours are morning 8, afternoon 13, evening 18", () => {
  assert.equal(SLOT_HOURS.morning, 8);
  assert.equal(SLOT_HOURS.afternoon, 13);
  assert.equal(SLOT_HOURS.evening, 18);
});

test("Monday morning in Prague is due at 08:00", () => {
  assert.equal(readerDue(pref(), mondayMorningPrague), true);
});

test("Monday morning in Prague is not due before 08:00", () => {
  assert.equal(readerDue(pref(), mondayEarlyPrague), false);
});

test("already sent this iso week is not due", () => {
  assert.equal(readerDue(pref({ last_sent_week: ISO }), mondayMorningPrague), false);
});

test("Monday-morning reader who sent this week is not due Tuesday", () => {
  assert.equal(isoWeekId(mondayMorningPrague, "Europe/Prague"), ISO);
  assert.equal(isoWeekId(tuesdayMorningPrague, "Europe/Prague"), ISO);
  assert.equal(readerDue(pref({ last_sent_week: ISO }), tuesdayMorningPrague), false);
});

test("Tuesday reader is due Tuesday morning", () => {
  assert.equal(readerDue(pref({ send_dow: 2 }), tuesdayMorningPrague), true);
  assert.equal(readerDue(pref({ send_dow: 2 }), mondayMorningPrague), false);
});

test("Friday evening is due at 18:00 Prague", () => {
  assert.equal(readerDue(pref({ send_dow: 5, send_slot: "evening" }), fridayEveningPrague), true);
});

test("Friday evening is not due at 17:30 Prague", () => {
  assert.equal(readerDue(pref({ send_dow: 5, send_slot: "evening" }), fridayAfternoonPrague), false);
});

test("Friday evening catch-up still sends on Saturday", () => {
  assert.equal(readerDue(pref({ send_dow: 5, send_slot: "evening" }), saturdayPrague), true);
});

test("New York is still before Monday morning when Prague is 08:00", () => {
  assert.equal(readerDue(pref({ timezone: "America/New_York" }), mondayMorningPrague), false);
});

test("opted-out prefs are never due", () => {
  assert.equal(readerDue(pref({ weekly: false }), mondayMorningPrague), false);
});

test("missing schedule defaults to Monday morning", () => {
  assert.equal(readerDue({ weekly: true }, mondayMorningPrague), true);
  assert.equal(readerDue({ weekly: true }, mondayEarlyPrague), false);
});

test("last 7 closed dates on Thursday are last Thursday through yesterday", () => {
  assert.deepEqual(lastClosedDates(thursdayAfternoonPrague, "Europe/Prague", 7), [
    "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08",
    "2026-11-09", "2026-11-10", "2026-11-11",
  ]);
});

test("last 7 closed dates on Monday are previous Monday through Sunday", () => {
  assert.deepEqual(lastClosedDates(mondayMorningPrague, "Europe/Prague", 7), [
    "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
    "2026-11-06", "2026-11-07", "2026-11-08",
  ]);
});

test("Tuesday pack is last Tuesday through yesterday, not this Monday only", () => {
  const dates = lastClosedDates(tuesdayMorningPrague, "Europe/Prague", 7);
  assert.deepEqual(dates, [
    "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06",
    "2026-11-07", "2026-11-08", "2026-11-09",
  ]);
  assert.equal(dates[0], "2026-11-03");
  assert.equal(dates[dates.length - 1], "2026-11-09");
  assert.notEqual(dates[0], "2026-11-09");
});

test("week label spans the rolling window", () => {
  assert.equal(weekLabel("2026-11-05", "2026-11-11"), "5\u201311 November 2026");
});

test("pack merges seven days and caps at 12 with domain and source limits", () => {
  const dates = lastClosedDates(thursdayAfternoonPrague, "Europe/Prague", 7);
  const days = {};
  dates.forEach((d) => { days[d] = { items: [], candidates: [] }; });
  const pool = [];
  for (let i = 0; i < 5; i++) {
    pool.push(dayItem("f" + i, {
      score: 100 - i,
      url: "https://flood.example/" + i,
      sources: ["hn"],
    }));
  }
  for (let i = 0; i < 6; i++) {
    pool.push(dayItem("h" + i, {
      score: 90 - i,
      url: "https://hn" + i + ".example/p",
      sources: ["hn"],
    }));
  }
  for (let i = 0; i < 12; i++) {
    pool.push(dayItem("u" + i, {
      score: 70 - i,
      url: "https://u" + i + ".example/p",
      sources: ["src" + i],
    }));
  }
  pool.forEach((it, i) => {
    const d = dates[i % dates.length];
    days[d].items.push(it);
    days[d].candidates.push(it);
  });
  const pack = packFromDays(days, dates);
  assert.equal(pack.period_start, "2026-11-05");
  assert.equal(pack.period_end, "2026-11-11");
  assert.equal(pack.items.length, WEEKLY_LIMIT);
  const fromDates = new Set(dates.filter((d) => days[d].items.some((it) =>
    pack.items.some((p) => p.url === it.url))));
  assert.ok(fromDates.size > 1, "merged more than one closed day");
  const flood = pack.items.filter((it) => it.url.includes("flood.example")).length;
  assert.equal(flood, 2);
  const hnCount = pack.items.filter((it) => (it.sources || [])[0] === "hn").length;
  assert.equal(hnCount, 4);
  assert.ok(pack.candidates.length >= pack.items.length);
  assert.ok(pack.candidates.length <= 60 + pack.items.length);
});

test("email intro is last seven days, never so far", () => {
  const pack = {
    label: "5–11 November 2026",
    items: [dayItem(1)],
  };
  const personal = render(pack, { items: [dayItem(1)], personal: true }, "");
  const published = render(pack, { items: [dayItem(1)], personal: false }, "");
  assert.match(personal.text, /The last seven days, ranked by your taste/);
  assert.match(published.text, /The last seven days as published/);
  assert.doesNotMatch(personal.html, /so far/);
  assert.doesNotMatch(published.html, /so far/);
  assert.doesNotMatch(personal.text, /so far/);
  assert.doesNotMatch(published.text, /so far/);
});
