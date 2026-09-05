# Kerning

A design and product digest you can read daily, weekly, or monthly. Pulls from
Hacker News, Lobsters, design and product publications, Substack, design-system
release feeds, and links shared on Bluesky. Ranks this calendar month, cuts
three editions, and learns from what you rate.

## Setup

```bash
pip install requests feedparser
```

## Running it

Two pieces. The Python script gathers and ranks; the HTML app is how you read
and rate.

**1. Build the digest**

```bash
python3 kerning_fetch.py --limit 12
```

Writes `digest.json` (read by the app) and `digest.md` (readable on its own).
One run builds today, this week (Monday–Sunday), and this month. The app
switches between them. Pass `--days 7` if you want a single rolling window
instead. X is skipped unless `APIFY_TOKEN` is set.

**2. Open the app**

```bash
python3 -m http.server 8000
```

Then go to <http://localhost:8000/kerning.html>.

You need the server. Opening the file directly with `file://` means the browser
blocks `fetch()` of `digest.json`, and the app silently falls back to querying
Hacker News live. If you see the "Live Hacker News only" banner, that's why.

**3. Close the loop**

On Taste, add people you follow and articles you like. Rate stories in the
digest too. Then Taste → Export profile. Save it beside the script as
`kerning-profile.json`. The next run ranks with those weights and watches
anyone you added, on top of the curated account lists.

## Files

| File | What it is |
|---|---|
| `kerning_fetch.py` | Fetching, merging, scoring. All the source config is at the top. |
| `kerning.html` | The reading app. Self-contained: HTML, CSS, and JS in one file. |
| `accounts.txt` | X handles to watch. One per line, `#` for comments. |
| `bsky-accounts.txt` | Bluesky handles to watch. Custom domains work. |
| `substack.txt` | Substack publications to watch. Slug, host, or URL. |
| `x-following.js` | Paste into the browser console to export your X following list. |
| `digest.json` | Generated. What the app reads. |
| `digest.md` | Generated. The digest as plain text. |

## Changing the look

Everything visual lives in the `<style>` block at the top of `kerning.html`.

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
over the digest. `--limit` sets how many items survive.

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

## X source (optional, paid)

Put the token in a local `.env` file (gitignored) or export it:

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

- Ratings and Taste live in one browser's local storage. Export the profile if
  you switch browsers.
- The X actor breaks whenever X changes its markup. It fails soft — the run
  carries on without that source.
- X needs `APIFY_TOKEN` in the environment or a local `.env`. Without it the
  run skips X and still builds from everything else, including Bluesky.
