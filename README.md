# Kerning

A design and product digest you can read daily, weekly, or monthly. Pulls from
Hacker News, Lobsters, design and product publications, Substack, design-system
release feeds, and links shared on Bluesky. Ranks this calendar month, cuts
yesterday’s best 4 plus this week and this month, and learns from what you
rate.

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
and asks you to try Refresh.

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
python3 kerning_fetch.py --limit 12
```

Writes `digest.json` (read by the app) and `digest.md` (readable on its own).
One run builds yesterday (4), this week (Monday–Sunday, 12), and this month
(12). Daily is the last complete calendar day, not today-so-far. The app
switches between them. Pass `--days 7` if you want a single rolling window
instead. X is skipped unless `APIFY_TOKEN` is set.

A forced rebuild is only needed when you want a new pass before the windows
change. Opening the app, or the nightly job, runs `kerning_fetch.py --if-stale`
and skips the network when the file is already current.

**2. Open the app**

```bash
python3 kerning_serve.py
```

Then go to <http://127.0.0.1:8000/index.html>.

You need this server, not `python3 -m http.server`. Plain `http.server` cannot
rebuild.

### Vercel (shared public digest)

<https://kerning-six.vercel.app/> is the single-user reader with Taste in the
browser. Recut runs in a function, not by rewriting the deployed `digest.json`.

Opening the page (or Refresh) `POST`s `/api/rebuild`. If Daily/Weekly/Monthly
are stale, that run fetches public sources (no X), writes the pack to Vercel
Blob, and `/api/digest` serves it. The first open after a window change can take
up to a few minutes. Refresh sends `{ force: true }`. A cron at 22:20 UTC
(~00:20 Prague in summer) recuts so the first visitor is not the one who waits.

In the Vercel project:

1. Create a Blob store and link it to this project (`BLOB_READ_WRITE_TOKEN`
   is added automatically).
2. Set `DIGEST_TZ=Europe/Prague` if it is not already set from `vercel.json`.
   Vercel reserves `TZ`; do not add it as a project variable.
3. Redeploy. Confirm `GET /api/digest` and that a stale Daily updates to
   yesterday.

Do not add `APIFY_TOKEN`. Do not point this project at the Fly FastAPI app.

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
| `index.html` | The reading app. Self-contained: HTML, CSS, and JS in one file. |
| `app/` | Hosted FastAPI, magic-link auth, Postgres models, crawl + cut jobs. |
| `kerning_lib/` | Calendar windows and digest cuts, shared by the CLI and the hosted worker. |
| `kerning_fetch.py` | Fetching, merging, scoring. All the source config is at the top. `--if-stale` skips a run when the windows are current. |
| `kerning_serve.py` | Local single-user server. Serves the app and rebuilds a stale digest on open. |
| `api/` | Vercel functions: `GET /api/digest`, `POST /api/rebuild`. |
| `vercel.json` | Static Vercel project, Python functions, nightly cron. Do not detect FastAPI. |
| `scripts/install-schedule.sh` | One-time install of the 00:20 LaunchAgent for the local path. |
| `accounts.txt` | X handles used as a Taste watchlist / ranking hints. Hosted fetch does not scrape X for these. |
| `bsky-accounts.txt` | Bluesky handles to watch. Custom domains work. |
| `substack.txt` | Substack publications to watch. Slug, host, or URL. |
| `x-following.js` | Paste into the browser console to export your X following list. |
| `digest.json` | Generated locally. Fallback snapshot on Vercel until Blob has a recut. |
| `digest.md` | Generated locally. The digest as plain text. |
| `docker-compose.yml` | Postgres + web + worker for the hosted app. |
| `.env.example` | Hosted secrets template (`DATABASE_URL`, mail, origin). |

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
