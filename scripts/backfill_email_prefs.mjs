#!/usr/bin/env node
// Insert email_prefs for every Auth user who has none.
// Existing rows are left alone (weekly off stays off).
//
//   SUPABASE_SERVICE_ROLE_KEY=... node scripts/backfill_email_prefs.mjs
//
// Logs counts, never addresses.

const SUPABASE_URL = process.env.SUPABASE_URL || "https://qypugamdqsykhkqwtmxi.supabase.co";
const DEFAULT_TZ = "Europe/Prague";

function redact(s) {
  return String(s).replace(/[^\s@"'<>]+@[^\s@"'<>]+\.[a-z]{2,}/gi, "[email]");
}

async function req(path, init) {
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) throw new Error("SUPABASE_SERVICE_ROLE_KEY is not set");
  const res = await fetch(SUPABASE_URL + path, Object.assign({}, init, {
    headers: Object.assign({
      apikey: key,
      Authorization: "Bearer " + key,
      "Content-Type": "application/json",
    }, (init && init.headers) || {}),
  }));
  if (!res.ok) {
    throw new Error(path.split("?")[0] + " failed: " + res.status + " " + (await res.text()));
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

async function listUsers() {
  const out = [];
  let page = 1;
  for (;;) {
    const data = await req("/auth/v1/admin/users?page=" + page + "&per_page=200");
    const users = (data && data.users) || [];
    out.push.apply(out, users);
    if (users.length < 200) break;
    page += 1;
  }
  return out;
}

async function listPrefs() {
  return (await req("/rest/v1/email_prefs?select=user_id,weekly")) || [];
}

async function insertRows(rows, withSchedule) {
  const body = rows.map((r) => {
    const row = {
      user_id: r.user_id,
      email: r.email,
      weekly: true,
      updated_at: new Date().toISOString(),
    };
    if (withSchedule) {
      row.send_dow = 1;
      row.send_slot = "morning";
      row.timezone = DEFAULT_TZ;
    }
    return row;
  });
  await req("/rest/v1/email_prefs", {
    method: "POST",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify(body),
  });
}

async function main() {
  const users = (await listUsers()).filter((u) => u && u.id && u.email);
  const prefs = await listPrefs();
  const have = {};
  let on = 0;
  let off = 0;
  prefs.forEach((p) => {
    have[p.user_id] = true;
    if (p.weekly) on += 1;
    else off += 1;
  });
  const missing = users.filter((u) => !have[u.id]).map((u) => ({
    user_id: u.id,
    email: u.email,
  }));
  console.log(users.length + " signed-in user(s), " + prefs.length + " email_prefs row(s) ("
    + on + " weekly on, " + off + " weekly off), " + missing.length + " missing.");
  if (!missing.length) {
    console.log("Nothing to insert.");
    return;
  }
  try {
    await insertRows(missing, true);
  } catch (err) {
    const msg = String(err.message || err);
    if (!/send_dow|send_slot|timezone|42703|PGRST204/i.test(msg)) throw err;
    console.log("Schedule columns missing; inserting weekly only.");
    await insertRows(missing, false);
  }
  console.log("Inserted " + missing.length + " email_prefs row(s), weekly on, Monday morning.");
}

main().catch((err) => {
  console.error(redact(err.message || err));
  process.exitCode = 1;
});
