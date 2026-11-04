import test from "node:test";
import assert from "node:assert/strict";
import { readerDue, SLOT_HOURS } from "../scripts/weekly_email.mjs";

const ISO = "2026-W45";
const mondayMorningPrague = new Date("2026-11-09T07:00:00Z"); // 08:00 Europe/Prague (CET)
const mondayEarlyPrague = new Date("2026-11-09T06:30:00Z"); // 07:30 Prague, before 08:00
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

test("slot hours are morning 8, afternoon 13, evening 18", () => {
  assert.equal(SLOT_HOURS.morning, 8);
  assert.equal(SLOT_HOURS.afternoon, 13);
  assert.equal(SLOT_HOURS.evening, 18);
});

test("Monday morning in Prague is due at 08:00", () => {
  assert.equal(readerDue(pref(), mondayMorningPrague, ISO), true);
});

test("Monday morning in Prague is not due before 08:00", () => {
  assert.equal(readerDue(pref(), mondayEarlyPrague, ISO), false);
});

test("already sent this iso week is not due", () => {
  assert.equal(readerDue(pref({ last_sent_week: ISO }), mondayMorningPrague, ISO), false);
});

test("Friday evening is due at 18:00 Prague", () => {
  assert.equal(readerDue(pref({ send_dow: 5, send_slot: "evening" }), fridayEveningPrague, ISO), true);
});

test("Friday evening is not due at 17:30 Prague", () => {
  assert.equal(readerDue(pref({ send_dow: 5, send_slot: "evening" }), fridayAfternoonPrague, ISO), false);
});

test("Friday evening catch-up still sends on Saturday", () => {
  assert.equal(readerDue(pref({ send_dow: 5, send_slot: "evening" }), saturdayPrague, ISO), true);
});

test("New York is still before Monday morning when Prague is 08:00", () => {
  assert.equal(readerDue(pref({ timezone: "America/New_York" }), mondayMorningPrague, ISO), false);
});

test("opted-out prefs are never due", () => {
  assert.equal(readerDue(pref({ weekly: false }), mondayMorningPrague, ISO), false);
});

test("missing schedule defaults to Monday morning", () => {
  assert.equal(readerDue({ weekly: true }, mondayMorningPrague, ISO), true);
  assert.equal(readerDue({ weekly: true }, mondayEarlyPrague, ISO), false);
});
