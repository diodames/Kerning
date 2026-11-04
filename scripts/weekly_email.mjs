#!/usr/bin/env node
// Weekly email: the current weekly issue, ranked by each opted-in reader's taste,
// sent on their chosen weekday and Morning / Afternoon / Evening.
//
//   node scripts/weekly_email.mjs [--dry-run] [--digest state/digest.json] [--out out]
//   node scripts/weekly_email.mjs --dry-run --profile kerning-profile.json --to you@example.com
//
// Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, RESEND_API_KEY, KERNING_MAIL_FROM,
// KERNING_MAIL_ONLY, KERNING_SITE_URL. The repo is public, so logs carry counts,
// never addresses.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { buildWeights, personalize, hasLearnedTaste, domainOf } = require("../taste.js");

const SUPABASE_URL = process.env.SUPABASE_URL || "https://qypugamdqsykhkqwtmxi.supabase.co";
const SITE_URL = (process.env.KERNING_SITE_URL || "https://www.kerningdigest.com/").replace(/\/?$/, "/");
const FROM = process.env.KERNING_MAIL_FROM || "Kerning <onboarding@resend.dev>";
const ONLY = (process.env.KERNING_MAIL_ONLY || "").trim().toLowerCase();
const DIGEST_TZ = process.env.DIGEST_TZ || "Europe/Prague";
const DEFAULT_TZ = "Europe/Prague";
const SLOT_HOURS = { morning: 8, afternoon: 13, evening: 18 };
const WEEKDAY_SHORT = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

function zonedParts(date, tz) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const parts = {};
  fmt.formatToParts(date).forEach((p) => { parts[p.type] = p.value; });
  return {
    year: +parts.year,
    month: +parts.month,
    day: +parts.day,
    hour: +parts.hour,
    minute: +parts.minute,
    dow: WEEKDAY_SHORT[parts.weekday],
  };
}

function isoWeekMinutes(parts) {
  const offset = parts.dow === 0 ? 6 : parts.dow - 1;
  return offset * 24 * 60 + parts.hour * 60 + parts.minute;
}

function readerDue(pref, now, isoWeek) {
  if (!pref || pref.weekly === false) return false;
  if (isoWeek && pref.last_sent_week === isoWeek) return false;
  let tz = pref.timezone || DEFAULT_TZ;
  let parts;
  try { parts = zonedParts(now, tz); }
  catch (e) { parts = zonedParts(now, DEFAULT_TZ); }
  const wantDow = pref.send_dow == null || pref.send_dow === "" ? 1 : Number(pref.send_dow);
  const slot = SLOT_HOURS[pref.send_slot] != null ? pref.send_slot : "morning";
  const wantHour = SLOT_HOURS[slot];
  const nowMin = isoWeekMinutes(parts);
  const wantMin = (wantDow === 0 ? 6 : wantDow - 1) * 24 * 60 + wantHour * 60;
  return nowMin >= wantMin;
}

export { SLOT_HOURS, readerDue };

function parseArgs(argv) {
  const args = { dryRun: false, digest: "state/digest.json", out: "out", profile: "", to: "" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--dry-run") args.dryRun = true;
    else if (a === "--digest") args.digest = argv[++i];
    else if (a === "--out") args.out = argv[++i];
    else if (a === "--profile") args.profile = argv[++i];
    else if (a === "--to") args.to = argv[++i];
    else throw new Error("Unknown argument: " + a);
  }
  return args;
}

function redact(s) {
  return String(s).replace(/[^\s@"'<>]+@[^\s@"'<>]+\.[a-z]{2,}/gi, "[email]");
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Same shape as mapDigestItems() in index.html.
function mapItems(items) {
  return (items || []).map((it) => ({
    id: String(it.id),
    title: it.title,
    url: it.url,
    hn: it.hn || it.url,
    points: it.points || 0,
    comments: it.comments || 0,
    created_at_i: it.created_at_i,
    sources: it.sources || [],
    authors: it.authors || [],
    reasons: (it.why || []).map((w) => [w, 1]),
    score: it.score || 0,
    total: it.score || 0,
  }));
}

function normalizeProfile(p) {
  const out = Object.assign({}, p || {});
  out.ratings = out.ratings || {};
  out.saved = out.saved || [];
  out.seeds = Object.assign({ people: [], resources: [], articles: [] }, out.seeds || {});
  return out;
}

function todayIn(tz) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date());
}

// Only a finished week counts as sent, so a midweek test run never blocks Monday's email.
function weekComplete(pack) {
  const end = pack.period_end || pack.week_end;
  return !!end && end < todayIn(DIGEST_TZ);
}

function rankFor(profile, pack) {
  const picks = mapItems(pack.items);
  const candidates = pack.candidates && pack.candidates.length ? mapItems(pack.candidates) : picks.slice();
  const p = normalizeProfile(profile);
  const weights = buildWeights(p, candidates);
  return { items: personalize(p, weights, candidates, picks), personal: hasLearnedTaste(p, weights) };
}

function itemMeta(it) {
  const bits = [domainOf(it.url)];
  const why = (it.reasons || []).map((r) => r[0]).filter(Boolean);
  if (why.length) bits.push(why[0]);
  return bits.filter(Boolean).join(" \u00b7 ");
}

// Mail apps turn bare domains into blue links; an explicit grey link keeps the row one colour.
function itemMetaHtml(it) {
  const domain = domainOf(it.url);
  const why = (it.reasons || []).map((r) => r[0]).filter(Boolean);
  const bits = [];
  if (domain) {
    bits.push(`<a href="${esc(it.url)}" style="color:#6b6b6b;text-decoration:none;">${esc(domain)}</a>`);
  }
  if (why.length) bits.push(esc(why[0]));
  return bits.join(" &middot; ");
}

function render(pack, ranked, unsubUrl, complete) {
  const label = pack.label || pack.week_label || "This week";
  const issue = complete ? "Last week\u2019s issue" : "This week\u2019s issue so far";
  const intro = ranked.personal
    ? issue + ", ranked by your taste."
    : issue + " as published. Rate a few stories on Kerning and next week\u2019s email follows your taste.";
  const subject = "Kerning \u00b7 " + label;

  const rows = ranked.items.map((it, i) => `
          <tr>
            <td style="width:32px;vertical-align:top;font-size:13px;color:#8a8a8a;padding:0 0 18px;font-variant-numeric:tabular-nums;">${String(i + 1).padStart(2, "0")}</td>
            <td style="vertical-align:top;padding:0 0 18px;">
              <a href="${esc(it.url)}" style="color:#1a1a1a;text-decoration:none;font-size:16px;line-height:1.4;font-weight:500;letter-spacing:-0.01em;">${esc(it.title)}</a>
              <div style="font-size:13px;line-height:1.5;color:#6b6b6b;padding-top:3px;">${itemMetaHtml(it)}</div>
            </td>
          </tr>`).join("");

  const footer = unsubUrl
    ? `You get this because you turned on the weekly email in your Kerning account.<br>
              <a href="${esc(unsubUrl)}" style="color:#8a8a8a;">Unsubscribe</a> &middot; <a href="${esc(SITE_URL)}" style="color:#8a8a8a;">${esc(SITE_URL.replace(/^https?:\/\//, "").replace(/\/$/, ""))}</a>`
    : `Preview. <a href="${esc(SITE_URL)}" style="color:#8a8a8a;">${esc(SITE_URL)}</a>`;

  const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no, url=no">
  <meta name="x-apple-disable-message-reformatting">
  <title>${esc(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f4f3f0;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f3f0;">
    <tr>
      <td align="center" style="padding:48px 20px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1a1a1a;">
          <tr>
            <td colspan="2" style="font-size:28px;font-weight:600;letter-spacing:-0.04em;padding:0 0 6px;">Kerning</td>
          </tr>
          <tr>
            <td colspan="2" style="font-size:14px;color:#6b6b6b;padding:0 0 20px;">${esc(label)}</td>
          </tr>
          <tr>
            <td colspan="2" style="font-size:16px;line-height:1.5;letter-spacing:-0.01em;padding:0 0 28px;">${esc(intro)}</td>
          </tr>${rows}
          <tr>
            <td colspan="2" style="padding:14px 0 32px;">
              <a href="${esc(SITE_URL)}" style="display:inline-block;background:#1a1a1a;color:#ffffff;text-decoration:none;font-size:15px;font-weight:500;padding:12px 22px;border-radius:999px;">Open Kerning</a>
            </td>
          </tr>
          <tr>
            <td colspan="2" style="font-size:13px;line-height:1.55;color:#8a8a8a;border-top:1px solid #dcdad5;padding:20px 0 0;">
              ${footer}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
`;

  const text = [
    "Kerning", label, "", intro, "",
    ...ranked.items.map((it, i) => (i + 1) + ". " + it.title + "\n   " + it.url + "\n   " + itemMeta(it)),
    "", "Open Kerning: " + SITE_URL,
    unsubUrl ? "Unsubscribe: " + unsubUrl : "",
  ].join("\n");

  return { subject: subject, html: html, text: text };
}

async function supabase(path, init) {
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) throw new Error("SUPABASE_SERVICE_ROLE_KEY is not set");
  const res = await fetch(SUPABASE_URL + "/rest/v1/" + path, Object.assign({}, init, {
    headers: Object.assign({
      apikey: key,
      Authorization: "Bearer " + key,
      "Content-Type": "application/json",
    }, (init && init.headers) || {}),
  }));
  if (!res.ok) throw new Error("Supabase " + path.split("?")[0] + " failed: " + res.status + " " + (await res.text()));
  return res.status === 204 ? null : res.json();
}

async function loadPrefs() {
  try {
    return await supabase("email_prefs?weekly=eq.true&select=user_id,email,unsub_token,last_sent_week,send_dow,send_slot,timezone");
  } catch (err) {
    const msg = String(err.message || err);
    if (!/send_dow|send_slot|timezone|42703|PGRST204/i.test(msg)) throw err;
    return await supabase("email_prefs?weekly=eq.true&select=user_id,email,unsub_token,last_sent_week");
  }
}

async function loadReaders(pack) {
  const prefs = await loadPrefs();
  const now = new Date();
  const due = prefs.filter((r) => readerDue(r, now, pack.iso_week));
  if (!due.length) return [];
  const ids = due.map((r) => r.user_id).join(",");
  const rows = await supabase("profiles?select=user_id,data&user_id=in.(" + ids + ")");
  const byId = {};
  rows.forEach((r) => { byId[r.user_id] = r.data; });
  return due.map((r) => ({
    userId: r.user_id,
    email: r.email,
    unsubUrl: SITE_URL + "?unsubscribe=" + encodeURIComponent(r.unsub_token),
    profile: byId[r.user_id] || {},
  }));
}

async function send(reader, mail) {
  const key = process.env.RESEND_API_KEY;
  if (!key) throw new Error("RESEND_API_KEY is not set");
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: FROM,
      to: [reader.email],
      subject: mail.subject,
      html: mail.html,
      text: mail.text,
      headers: { "List-Unsubscribe": "<" + reader.unsubUrl + ">" },
    }),
  });
  if (!res.ok) throw new Error("Resend " + res.status + " " + (await res.text()));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const digest = JSON.parse(readFileSync(args.digest, "utf8"));
  const pack = (digest.cadences || {}).weekly;
  if (!pack || !(pack.items || []).length) {
    console.log("No weekly issue in " + args.digest + "; nothing to send.");
    return;
  }
  const complete = weekComplete(pack);
  console.log("Issue " + (pack.iso_week || "?") + " (" + (pack.label || "") + "), "
    + (complete ? "complete" : "still running"));

  let readers;
  if (args.profile || args.to) {
    const profile = args.profile ? JSON.parse(readFileSync(args.profile, "utf8")) : {};
    readers = [{ userId: "local", email: args.to || "you@example.com", unsubUrl: "", profile: profile }];
  } else {
    readers = await loadReaders(pack);
  }
  const total = readers.length;
  if (ONLY) readers = readers.filter((r) => String(r.email).toLowerCase() === ONLY);
  console.log(total + " reader(s) due, " + readers.length + " after KERNING_MAIL_ONLY.");

  if (args.dryRun) mkdirSync(args.out, { recursive: true });
  let sent = 0, failed = 0;
  for (let i = 0; i < readers.length; i++) {
    const reader = readers[i];
    const ranked = rankFor(reader.profile, pack);
    // Previews can land in a public artifact, so they never carry a real token.
    const unsubUrl = args.dryRun && reader.unsubUrl ? SITE_URL + "?unsubscribe=preview" : reader.unsubUrl;
    const mail = render(pack, ranked, unsubUrl, complete);
    const tag = "reader " + (i + 1) + (ranked.personal ? " (personal)" : " (published picks)");
    if (args.dryRun) {
      const base = join(args.out, "weekly-" + (i + 1));
      writeFileSync(base + ".html", mail.html);
      writeFileSync(base + ".txt", mail.subject + "\n\n" + mail.text);
      console.log("Wrote " + base + ".html, " + tag);
      continue;
    }
    try {
      await send(reader, mail);
      if (pack.iso_week && reader.userId !== "local") {
        await supabase("email_prefs?user_id=eq." + reader.userId, {
          method: "PATCH",
          headers: { Prefer: "return=minimal" },
          body: JSON.stringify({ last_sent_week: pack.iso_week }),
        });
      }
      sent++;
      console.log("Sent " + tag);
    } catch (err) {
      failed++;
      console.error("Failed " + tag + ": " + redact(err.message));
    }
  }
  if (!args.dryRun) console.log("Sent " + sent + ", failed " + failed + ".");
  if (failed) process.exitCode = 1;
}

function invokedDirectly() {
  try {
    return fileURLToPath(import.meta.url) === resolve(process.argv[1] || "");
  } catch (e) {
    return false;
  }
}

if (invokedDirectly()) {
  main().catch((err) => {
    console.error(redact(err.message || err));
    process.exitCode = 1;
  });
}
