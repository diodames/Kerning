# Kerning

A design and product digest you can read daily, weekly, or monthly. Pulls from
Hacker News, Lobsters, design and product publications, Substack, design-system
release feeds, and links shared on Bluesky. Ranks this calendar month, cuts
yesterday’s best 4 plus the weekly edition and this month, and learns from
what you rate. Weekly is last week on Monday, and this week from Tuesday.

There are two ways to run it.

## Hosted app (per-user)

Each signed-in person has their own Taste and their own Daily, Weekly, and
Monthly digest. Sign-in is a magic link (no passwords). Hosted fetch does not
scrape X.

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
# In one terminal:
uvicorn app.main:app --reload --port 8000
# In another:
python3 -m app.worker
```

Open <http://127.0.0.1:8000/>. Enter your email. With no `RESEND_API_KEY` the
landing page shows a local sign-in link (also printed in the web process log).

Or with Postgres:

```bash
docker compose up --build
```

If a personal digest cannot be built, the app falls back to live Hacker News
and offers Try again.

### Production (Fly.io)

Phone and desktop share one account once this is on HTTPS with magic-link
mail. Stay on `*.fly.dev` for now. Until you verify a sending domain, Resend
only delivers to the email on the Resend account — enough for you on two
devices.

Sign in on the Mac first. The first signed-in browser uploads localStorage
Taste if the server profile is empty. Then sign in on the phone with the same
email. If the phone goes first with an empty profile, it can overwrite Taste.

```bash
fly auth login
fly postgres create --name kerning-db --region ams
fly postgres attach kerning-db
fly secrets set \
  SECRET_KEY="$(openssl rand -hex 32)" \
  RESEND_API_KEY=re_... \
  MAIL_FROM="Kerning <beth.t@example.com>" \
  APP_ORIGIN=https://kerning.fly.dev
fly deploy
fly scale count worker=1
```

`MAIL_FROM` can stay Resend’s onboarding sender until you own a domain.
Confirm `GET https://kerning.fly.dev/health` and that worker logs show crawl
or cut, not a crash loop.

The worker crawls public sources, cuts each user’s digest in their timezone,
and enqueues a nightly pass at 00:20. Rebuilds from the app are queued; they
do not block the request.

## Local single-user (this Mac)

One `digest.json` on disk, Taste in this browser. No accounts.

```bash
pip install requests feedparser
```

**1. Build the digest (optional)**

```bash
python3 kerning_fetch.py
```

Collects public sources into `data/pool.json` (no ranking), then closes
yesterday in Europe/Prague and writes `digest.json`. Daily is the last
complete calendar day (4 stories). Weekly and Monthly are composed only
from closed days (12 each). Weekly is last week on Monday, and this
Monday–Sunday from Tuesday. Pass `--collect` or `--close` to run one
phase. Pass `--days 7` for the old one-shot rolling window. X is skipped
unless `APIFY_TOKEN` is set.

Opening the app does not recut. The nightly LaunchAgent runs
`kerning_fetch.py --if-stale` and skips when the windows are current.

**2. Open the app**

```bash
python3 kerning_serve.py
```

Then go to <http://127.0.0.1:8000/index.html>.

You need this server, not `python3 -m http.server`, if you want a local
`POST /rebuild`. The reader itself only loads `digest.json`.

**Weekly empty or stuck loading**

Serve with `python3 kerning_serve.py` so `digest.json` is reachable. Plain
`python3 -m http.server` still serves the file; it cannot recut.

Three screens mean different things:

- **Dates without “Last week” / “This week”** — the file is an older pack.
  The app shows those stories at once. Run `python3 kerning_fetch.py` (or
  the LaunchAgent) to close a new day.
- **Vacant** (“Nothing in last week’s digest” on Monday, or this week’s
  from Tuesday) — that pack has no stories. Monthly may still be current.
- **Spinner** (“Opening last week’s digest” on Monday) — must clear as soon
  as `digest.json` loads.

Vacant Weekly on a Monday used to mean the recut targeted the week that had
just started — often empty — and overwrote the closed Monday–Sunday pack.
Monday now keeps last week; this week starts Tuesday.

If a recut hangs:

```bash
ps aux | grep kerning_fetch
```

A lock held too long is `.digest-fetch.lock` in the repo, or
`/tmp/.digest-fetch.lock` if the repo is not writable. The next fetch steals a
lock older than 280 seconds. You can also delete that file and reopen the app.

### Vercel (shared public digest)

<https://kerning-six.vercel.app/> is the single-user reader with Taste in the
browser. Opening the page only `GET`s `/api/digest`, which serves
`digest.json` from the repo's `data` branch (edge-cached for ten minutes).

GitHub Actions does the work and commits the results to `data`:

1. **Collect** every two hours (`.github/workflows/collect.yml`) runs
   `kerning_fetch.py --collect` and upserts public sources (no X) into
   `pool.json`.
2. **Close** after Prague midnight (`close.yml`, 23:15 UTC with a 05:15 UTC
   backup) ranks yesterday's pool, writes an immutable `days/YYYY-MM-DD.json`,
   composes Weekly/Monthly from closed days, and refreshes `digest.json`.

Close also backfills any missing day in the Weekly and Monthly windows from
publish dates, so a fresh pool or a missed run never leaves gaps.
If Daily comes out empty, it shows the latest closed day from the past
week. Any edition that is still empty keeps its last non-empty pack.
A repeat close without `force` changes nothing.

Both workflows share one concurrency group, so pushes to `data` never race.
`vercel.json` turns off deployments for the `data` branch.

This replaced Vercel Blob, whose Hobby allowance (2,000 advanced operations a
month) ran out and suspended the store. The `/api/collect` and `/api/close`
functions still exist for Blob but nothing schedules them.

**Regenerate a closed day**

Run the **Close day** workflow by hand (Actions, Run workflow) with a date and
`force` set to `true`, or locally:

```bash
KERNING_DATA_DIR=path/to/data-checkout python3 kerning_fetch.py --close --date 2026-09-27 --force
```

Each closed day has a `days/YYYY-MM-DD.stats.json` with drop counts
(`prerelease`, `blocklist`, `below_threshold`, `lexicon`, …).

### Profiles and sync

**Your own ranking.** Each closed day keeps its top 30 `candidates` next to
the 4 published picks. Every edition in `digest.json` carries candidates too
(Daily 30, Weekly 60, Monthly 100). Once you rate stories or add people and
articles on Taste, the browser reranks those candidates by your learned
weights (published score + 2 × taste) with the same per-domain and
per-source caps as the close, and shows as many as the edition publishes.
Without any taste the published picks show unchanged. Days closed before
candidates existed offer only their picks.

**Sync across devices** is optional and free on Supabase. Signed out, the
profile stays in this browser as before. Signed in with an emailed link, the
browser pulls the stored profile, merges it with the local one, and pushes
the result back when it changes. It syncs on load, one second after an
edit, and when the tab comes back into view.

Merging works per entry, so two devices editing at once never overwrite
each other. Every rating, saved story, person, resource, and article
carries `mt`, the time it last changed. Removing one writes a tombstone in
`deleted`. The newer entry wins unless a newer tombstone removed it.
Tombstones expire after 90 days. Catalog defaults start at `mt` 0, so a
fresh device seeding them never revives one you deleted. Learned weights are
not stored; each browser rebuilds them after a merge. The logic lives in
`merge.js`, the ranking in `taste.js`; test both with `node --test tests/*.mjs`.

Setup:

1. Create a free project at [supabase.com](https://supabase.com).
2. Authentication → Sign In / Providers: keep Email on (magic link). Under
   URL Configuration set Site URL to `https://kerning-six.vercel.app` and add
   `http://localhost:8000/**` to Redirect URLs.
3. SQL editor:

   ```sql
   create table public.profiles (
     user_id uuid primary key references auth.users on delete cascade,
     data jsonb not null default '{}'::jsonb,
     updated_at timestamptz not null default now()
   );
   alter table public.profiles enable row level security;
   create policy "own profile" on public.profiles
     for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
   ```

4. Project Settings → API: copy the Project URL and the anon public key into
   `SUPABASE_URL` and `SUPABASE_ANON_KEY` in `index.html`. Both are meant to
   be public; row-level security keeps each profile readable only by its
   owner. With either left empty, the Sync button stays hidden.

Free-plan limits: a project pauses after a week without requests (resume it
from the dashboard; profiles are kept), and the built-in mailer sends only a
few sign-in emails an hour. Add custom SMTP under Authentication if that
gets in the way.

**Account page.** The Sign in tab becomes Account once you're signed in. It
shows what's synced, the last sync time, Sync now, and Delete synced data. Delete removes
the `profiles` and `email_prefs` rows and signs out; this browser keeps its
copy. The Supabase login itself stays, because deleting a user needs the
service_role key, which never goes in the browser. Remove it from
Authentication → Users if asked.

### Weekly email

An opt-in email every Monday with last week's issue, ranked by the reader's
synced taste (the same `taste.js` the site uses). A GitHub Action
(`.github/workflows/weekly-email.yml`, Monday 06:30 UTC, after the 05:15 close) runs
`scripts/weekly_email.mjs`, which reads `digest.json` from the `data` branch,
loads opted-in readers and their profiles with the service role key, and
sends through [Resend](https://resend.com) (free: 3,000 emails a month,
100 a day). Each reader gets at most one email per ISO week.

Setup:

1. SQL editor in Supabase:

   ```sql
   create table public.email_prefs (
     user_id uuid primary key references auth.users on delete cascade,
     email text not null,
     weekly boolean not null default false,
     unsub_token uuid not null unique default gen_random_uuid(),
     last_sent_week text,
     updated_at timestamptz not null default now()
   );
   alter table public.email_prefs enable row level security;
   create policy "own email prefs" on public.email_prefs
     for all using (auth.uid() = user_id)
     with check (auth.uid() = user_id and email = auth.email());

   create function public.unsubscribe(token uuid) returns boolean
   language sql security definer set search_path = public as $$
     with hit as (
       update public.email_prefs set weekly = false, updated_at = now()
       where unsub_token = token
       returning 1
     )
     select exists (select 1 from hit);
   $$;
   revoke all on function public.unsubscribe(uuid) from public;
   grant execute on function public.unsubscribe(uuid) to anon, authenticated;
   ```

2. Create a Resend account and an API key (Sending access).
3. GitHub → Settings → Secrets and variables → Actions, add:
   - `SUPABASE_SERVICE_ROLE_KEY`: Supabase → Project Settings → API keys →
     service_role. It bypasses row-level security, so it lives only here.
   - `RESEND_API_KEY`: the key from step 2.
   - `KERNING_MAIL_ONLY`: your own address while Resend has no verified
     domain. Resend's test sender (`onboarding@resend.dev`) delivers only to
     the account's own email, so every other reader is skipped.
4. Run the workflow by hand with `dry_run` on to see the rendered emails in
   the run's artifact, then once with it off.

The opt-in checkbox on the Account page is hidden until
`WEEKLY_EMAIL_OPEN` in `index.html` is `true`. Until then, open the site
once with `?beta=email` to show it in that browser. To open it to everyone:
verify a domain in Resend, set the `KERNING_MAIL_FROM` repository variable
(for example `Kerning <digest@yourdomain.com>`), delete `KERNING_MAIL_ONLY`,
and flip the constant.

Each email carries an unsubscribe link (`/?unsubscribe=<token>`) and a
`List-Unsubscribe` header. The link calls `unsubscribe()`, which turns the
email off without signing in.

Preview locally without sending:

```bash
node scripts/weekly_email.mjs --dry-run --digest path/to/digest.json \
  --profile kerning-profile.json --to you@example.com
```

Opening the file directly with `file://` means the browser blocks
`fetch()` of `digest.json`, and the app silently falls back to querying
Hacker News live. If you see the "Live Hacker News only" banner, that's why.

**3. Nightly rebuild**

Once, from the repo:

```bash
bash scripts/install-schedule.sh
```

That installs a LaunchAgent which runs at 00:20 local and fetches only if
Daily, Weekly, or Monthly are stale. Unload it with
`launchctl unload ~/Library/LaunchAgents/com.kerning.fetch.plist`.

**4. Close the loop**

On Taste → Sources, add people you follow and resources you watch (RSS,
GitHub, Substack). On Taste, add articles you like. Rate stories in the
digest too. Then export the profile from Taste. Save it beside the script
as `kerning-profile.json`. The next run ranks with those weights and
watches anyone and any feed you added, on top of the curated lists.

## Files

| File | What it is |
|---|---|
| `index.html` | The reading app: HTML, CSS, and JS in one file, plus `taste.js` and `merge.js`. |
| `taste.js` | Tokens, learned weights, and the personal rerank; shared with the weekly email. |
| `merge.js` | Per-entry profile merge for sync across devices. |
| `scripts/weekly_email.mjs` | Monday email: personal ranking per opted-in reader, sent through Resend. |
| `app/` | Hosted FastAPI, magic-link auth, Postgres models, crawl + cut jobs. |
| `kerning_lib/` | Windows, pool, quality gate, collect/close, Blob/local store. |
| `kerning_lib/quality.json` | Close-time thresholds, GitHub pre-release rules, domain lists. |
| `kerning_fetch.py` | Fetching, merging, scoring. `--collect` / `--close` / `--if-stale`. |
| `kerning_serve.py` | Local single-user server. Serves the app; `POST /rebuild` is opt-in. |
| `api/` | Vercel: `GET /api/digest` (from the `data` branch); unused Blob collect/close. |
| `vercel.json` | Static Vercel project, Python functions, no builds for `data`. |
| `.github/workflows/` | Collect every 2h and close after Prague midnight, into `data`; Monday weekly email. |
| `scripts/install-schedule.sh` | One-time install of the 00:20 LaunchAgent for the local path. |
| `accounts.txt` | X handles used as a Taste watchlist / ranking hints. Hosted fetch does not scrape X for these. |
| `bsky-accounts.txt` | Bluesky handles to watch. Custom domains work. |
| `substack.txt` | Substack publications to watch. Slug, host, or URL. |
| `x-following.js` | Paste into the browser console to export your X following list. |
| `digest.json` | Generated locally. Fallback snapshot when `/api/digest` fails. |
| `digest.md` | Generated locally. The digest as plain text. |
| `docker-compose.yml` | Postgres + web + worker for the hosted app. |
| `.env.example` | Secrets template (`DATABASE_URL`, mail, origin, `CRON_SECRET`). |

## Changing the look

Everything visual lives in the `<style>` block at the top of `index.html`.

Colours are five CSS variables under `:root` — `--paper`, `--ink`, `--flame`,
`--moss`, `--chalk`. Change those and the whole app follows.

Type is two families doing two jobs: Georgia for headlines (`.k-mark`, `a.title`,
`.empty h2`), system sans for everything else. Swapping either is a one-line
change in those rules.

Layout is `li.item` — a flex row of the rank numeral (`.rank`) and the body
(`.body`). The story list has hairline separators rather than cards; if you want
cards, put a background and border on `li.item` and drop the `border-bottom`.

The markup is generated in `itemHTML()`, about two thirds down the script.

## Tuning the ranking

The `W` dictionary near the top of `kerning_fetch.py` holds the scoring weights.
`corroboration` is deliberately the largest — a link surfacing in two places
independently beats one with more upvotes in a single place.

`MAX_PER_DOMAIN` and `MAX_PER_SOURCE` stop any one blog or aggregator taking
over the digest. `--limit` sets how many items survive in weekly and monthly
editions. Daily is always yesterday’s best 4.

## Substack source (free, no login)

Every publication exposes RSS at `/feed`. The script reads `substack.txt` and
treats each newsletter as a curated publication. Edit that file to change who
you watch — a slug (`lookingglass`), a host, or a full URL all work. Paid
posts only appear as titles.

## Bluesky source (free, no login)

Author feeds are public. The script reads `bsky-accounts.txt` and treats shared
links like the X source — including a buzz score from likes, reposts, and
replies. Edit that file to change who you watch.

Bluesky turned off anonymous *search*. If you want search on top of the feeds:

```bash
export BSKY_HANDLE=you.bsky.social
export BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

## X source (optional, local only)

Hosted Kerning never calls Apify. On this Mac, put the token in a local `.env`
file (gitignored) or export it:

```bash
# .env
APIFY_TOKEN=apify_api_xxxxx
```

```bash
python3 kerning_fetch.py --verify-accounts
```

Roughly $0.32 a run at the default 800-tweet cap on a paid Apify plan.
Free plans only return 10 tweets (demo mode) — that’s why a first run looks empty.
`--verify-accounts` reports which handles actually posted, so you can prune
`accounts.txt` on evidence.

Scraping X is against its terms of service. That's your call to make knowingly;
for a personal reading list the practical risk is negligible.

## Known rough edges

- On the hosted app, Taste lives with your account. Export still downloads JSON.
- The local single-user path keeps ratings in this browser. Export the profile if
  you switch browsers.
- The X actor breaks whenever X changes its markup. It fails soft — the run
  carries on without that source.
- X needs `APIFY_TOKEN` in the environment or a local `.env`. Without it the
  local run skips X and still builds from everything else, including Bluesky.
