#!/usr/bin/env python3
"""
Kerning — a design and product digest you can read daily, weekly, or monthly.

Pulls from Hacker News, Lobsters, design and product publications, Substack,
and the release feeds of major design systems. Merges everything by canonical
URL, then cuts three ranked editions from this calendar month.

    pip install requests feedparser
    python3 kerning_fetch.py --limit 12

Writes digest.json (for the Kerning web app) and digest.md (to read directly).
Pass --days N for a single rolling window instead.

Bluesky is a first-class source: public author feeds, no login. Search-based
buzz still needs credentials if you want it on top:

    export BSKY_HANDLE=you.bsky.social
    export BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser
import requests

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path=None):
    """Load KEY=VAL from a local .env. Existing environment variables win."""
    path = path or os.path.join(_HERE, ".env")
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val


load_env()

UA = "kerning-digest/1.0 (personal reading list; +https://example.invalid)"
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": UA})

# --------------------------------------------------------------------------
# Sources. Edit freely — everything below adapts.
# --------------------------------------------------------------------------

HN_QUERIES = [
    "design", "typography", "typeface", "fonts", "UX", "user interface",
    "usability", "accessibility", "design system", "figma", "CSS",
    "web design", "icons", "illustration", "interaction design",
    "product management", "product discovery", "product manager",
    "jobs to be done", "product strategy", "user research",
]

LOBSTERS_TAGS = ["design", "css", "web"]

# Human-curated or editorially filtered. A person already said yes to these,
# so they get a curation bonus in the scoring.
CURATED_FEEDS = {
    "NN/g":               "https://www.nngroup.com/feed/rss/",
    "Smashing Magazine":  "https://www.smashingmagazine.com/feed/",
    "A List Apart":       "https://alistapart.com/main/feed/",
    "UX Collective":      "https://uxdesign.cc/feed",
    "Sidebar":            "https://sidebar.io/feed.xml",
    "Typographica":       "https://typographica.org/feed/",
    "SVPG":               "https://www.svpg.com/feed",
    "Product Talk":       "https://www.producttalk.org/feed",
    "Intercom":           "https://www.intercom.com/blog/feed",
}

# Design systems and primitives. Release notes are the earliest, highest-
# fidelity signal about how software design is actually changing.
GITHUB_REPOS = {
    "Primer (GitHub)":   "primer/react",
    "Polaris (Shopify)": "Shopify/polaris",
    "Carbon (IBM)":      "carbon-design-system/carbon",
    "Spectrum (Adobe)":  "adobe/react-spectrum",
    "Radix":             "radix-ui/primitives",
    "shadcn/ui":         "shadcn-ui/ui",
    "Tailwind CSS":      "tailwindlabs/tailwindcss",
}

# X accounts whose shared links are worth watching. This is a STARTING LIST,
# not a verified one — handles change, and a lot of design people moved to
# Bluesky. Run `--verify-accounts` to see which of these actually return
# anything, then delete the dead ones. Organisation handles are far more
# stable than personal ones.
X_ACCOUNTS = [
    # publications and orgs
    "smashingmag", "alistapart", "nngroup", "typographica", "fontsinuse",
    "ilovetypography", "itsnicethat", "dezeen", "awwwards", "figma",
    "googledesign", "webkit",
    # practitioners
    "zeldman", "brad_frost", "jina", "lukew", "adactio", "jensimmons",
    "rachelandrew", "heydonworks", "sarah_edo", "adamwathan", "shadcn",
    "steveschoger", "joulee", "jmspool", "vitalyf", "erikdkennedy",
    "frankchimero", "mrmrs_",
]

APIFY_ACTOR = "apidojo~twitter-scraper-lite"  # no 50-tweet minimum; override with APIFY_ACTOR
X_ACCOUNTS_PER_QUERY = 14               # actor allows at most 5 searchTerms per run
X_MAX_SEARCH_TERMS = 5
X_MAX_TWEETS = 800                      # hard cost ceiling per run
X_DEMO_CAP = 10                         # Apify free-plan demo returns at most this many
X_MIN_SHARERS_FOR_LOOKUP = 2            # only chase titles for corroborated links
BSKY_FEED_PAGES = 3                     # 50 posts each; stop once older than --days
BSKY_MIN_SHARERS_FOR_LOOKUP = 2

LEXICON = [
    ("typography", 3, ("typographic",)),
    ("typeface", 3), ("typesetting", 3), ("kerning", 3),
    ("font", 3, ("fonts",)), ("lettering", 3), ("type design", 3),
    ("figma", 3),
    ("design system", 3, ("design systems",)),
    ("design token", 3, ("design tokens",)),
    ("ux", 3, ("user experience",)),
    ("ui", 3, ("user interface",)),
    ("usability", 3),
    ("interaction design", 3), ("visual design", 3), ("graphic design", 3),
    ("product design", 3), ("information architecture", 3), ("wireframe", 3),
    ("human interface", 3), ("material design", 3), ("skeuomorph", 3),
    ("bauhaus", 3), ("illustration", 3), ("iconography", 3),
    ("accessibility", 3, ("a11y",)),
    ("wcag", 3), ("screen reader", 3), ("motion design", 3),
    ("brand identity", 3), ("color palette", 3), ("grid system", 3),
    ("web design", 3), ("legibility", 3), ("logo", 3),
    ("icons", 2), ("branding", 2), ("palette", 2), ("layout", 2), ("css", 2),
    ("svg", 2), ("animation", 2),
    ("prototype", 2, ("prototyping",)),
    ("dark mode", 2),
    ("aesthetic", 2, ("aesthetics",)),
    ("designer", 2), ("redesign", 2), ("readability", 2),
    ("responsive", 2),
    ("product strategy", 2), ("product sense", 2), ("roadmap", 2),
    ("prioritization", 2), ("prd", 2), ("user research", 2),
    ("outcome-based", 2), ("product-led", 2),
    ("product management", 3), ("product manager", 3),
    ("product discovery", 3),
    ("jobs to be done", 3, ("jtbd",)),
    ("opportunity solution tree", 3), ("dual-track", 3),
    ("continuous discovery", 3), ("product ops", 3),
    ("design", 1), ("interface", 1), ("craft", 1),
]

STOP = set(
    "the a an and or of for to in on with from this that how why what your you are "
    "is it its at as be by we our not new using use can show ask hn i my me was were "
    "has have had but if then than so out up more most about into over after before "
    "all any some one two three via just like get got make makes made does here there "
    "when who will would should could".split()
)

# Scoring weights. Corroboration is deliberately the loudest signal.
W = {
    "corroboration": 3.4,   # same link surfacing in more than one place
    "relevance":     1.0,   # design lexicon match
    "attention":     0.9,   # upvotes, log-scaled
    "debate":        0.8,   # comments per upvote — argument, not drive-by votes
    "buzz":          1.1,   # Bluesky discussion
    "curation":      1.6,   # an editor already chose it
    "taste":         2.0,   # your learned profile
    "recency":       1.2,
}

MAX_PER_DOMAIN = 2
MAX_PER_SOURCE = 4
SHORTLIST = 40          # how many candidates get a buzz lookup

# --------------------------------------------------------------------------
# URL canonicalisation — the backbone of cross-source merging
# --------------------------------------------------------------------------

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref|ref_src|source|si$)", re.I)


def this_week(now=None):
    """Monday 00:00 local through next Monday 00:00."""
    now = now or datetime.now().astimezone()
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


def this_day(now=None):
    now = now or datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def this_month(now=None):
    now = now or datetime.now().astimezone()
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


RECENCY_TAU = {"daily": 1.5, "weekly": 21, "monthly": 45}


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


def canonical(url: str) -> str:
    """Reduce a URL to a comparable key so the same link merges across sources."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()
    if not p.netloc:
        return url.strip().lower()

    host = p.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]

    path = re.sub(r"/+$", "", p.path) or "/"
    if host in ("youtu.be",):
        host, path = "youtube.com", "/watch"

    query = urlencode(
        [(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)]
    )
    return urlunparse(("https", host, path, "", query, ""))


def domain_of(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except ValueError:
        return ""


# --------------------------------------------------------------------------
# Relevance and taste
# --------------------------------------------------------------------------

def _lexicon_form_hits(hay: str, form: str) -> bool:
    if " " in form:
        return form in hay
    return bool(re.search(rf"\b{re.escape(form)}\b", hay))


def _lexicon_parts(entry):
    term, weight = entry[0], entry[1]
    aliases = entry[2] if len(entry) > 2 else ()
    return term, weight, aliases


def _lexicon_entry_hits(hay: str, entry) -> bool:
    term, _, aliases = _lexicon_parts(entry)
    if _lexicon_form_hits(hay, term):
        return True
    return any(_lexicon_form_hits(hay, a) for a in aliases)


def lexicon_score(title: str, url: str) -> int:
    hay = f"{title} {domain_of(url)}".lower()
    total = 0
    for entry in LEXICON:
        if _lexicon_entry_hits(hay, entry):
            total += entry[1]
    return total


def tokens_of(title: str, url: str, authors=None):
    """Design topics from the lexicon, plus publisher and author tokens."""
    hay = f"{title or ''} {domain_of(url)}".lower()
    words = set()
    for entry in LEXICON:
        term, weight, _ = _lexicon_parts(entry)
        if weight < 2:
            continue
        if _lexicon_entry_hits(hay, entry):
            words.add(term)
    d = domain_of(url)
    if d:
        words.add(f"site:{d}")
    for a in authors or []:
        if a:
            words.add(f"person:{str(a).lower()}")
    return words


def taste_score(title: str, url: str, weights: dict, authors=None) -> float:
    if not weights:
        return 0.0
    toks = tokens_of(title, url, authors)
    if not toks:
        return 0.0
    return sum(weights.get(t, 0) for t in toks) / math.sqrt(len(toks))


def downvoted_urls(profile_data) -> set:
    """Canonical URLs the reader marked less like this."""
    out = set()
    ratings = (profile_data or {}).get("ratings") or {}
    for rec in ratings.values():
        if not rec or rec.get("r", 0) >= 0:
            continue
        key = canonical(rec.get("url") or "")
        if key:
            out.add(key)
    return out


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

def _get(url, **kw):
    kw.setdefault("timeout", 20)
    r = HTTP.get(url, **kw)
    r.raise_for_status()
    return r


def fetch_hn(days: int):
    since = int(time.time()) - days * 86400
    out = []

    def one(q):
        try:
            r = _get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": q, "tags": "story",
                    "numericFilters": f"created_at_i>{since}",
                    "hitsPerPage": 40,
                },
            )
            return r.json().get("hits", [])
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=8) as ex:
        for hits in ex.map(one, HN_QUERIES):
            for h in hits:
                if not h.get("title"):
                    continue
                oid = h["objectID"]
                out.append({
                    "title": h["title"].strip(),
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                    "discussion": f"https://news.ycombinator.com/item?id={oid}",
                    "source": "Hacker News",
                    "points": h.get("points") or 0,
                    "comments": h.get("num_comments") or 0,
                    "ts": h.get("created_at_i") or 0,
                })
    return out


def fetch_lobsters(days: int):
    cutoff = time.time() - days * 86400
    out = []
    for tag in LOBSTERS_TAGS:
        try:
            data = _get(f"https://lobste.rs/t/{tag}.json").json()
        except Exception:
            continue
        for s in data:
            try:
                ts = datetime.fromisoformat(
                    s["created_at"].replace("Z", "+00:00")
                ).timestamp()
            except Exception:
                ts = time.time()
            if ts < cutoff:
                continue
            out.append({
                "title": (s.get("title") or "").strip(),
                "url": s.get("url") or s.get("short_id_url", ""),
                "discussion": s.get("comments_url", ""),
                "source": "Lobsters",
                "points": s.get("score") or 0,
                "comments": s.get("comment_count") or 0,
                "ts": ts,
            })
    return out


def _entry_ts(e):
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(e, key, None) or e.get(key)
        if t:
            return time.mktime(t)
    return time.time()


def fetch_feeds(days: int, feeds=None):
    cutoff = time.time() - days * 86400
    out = []
    feeds = feeds if feeds is not None else CURATED_FEEDS

    def one(item):
        name, url = item
        try:
            parsed = feedparser.parse(url, agent=UA)
        except Exception:
            return []
        rows = []
        for e in parsed.entries[:30]:
            ts = _entry_ts(e)
            if ts < cutoff:
                continue
            link = e.get("link") or ""
            if not link or not e.get("title"):
                continue
            rows.append({
                "title": e["title"].strip(),
                "url": link,
                "discussion": "",
                "source": name,
                "points": 0,
                "comments": 0,
                "ts": ts,
                "curated": True,
            })
        return rows

    with ThreadPoolExecutor(max_workers=6) as ex:
        for rows in ex.map(one, feeds.items()):
            out.extend(rows)
    return out


def fetch_releases(days: int, repos=None):
    """Design system releases via GitHub's per-repo Atom feed. No token needed."""
    cutoff = time.time() - days * 86400
    out = []
    repos = repos if repos is not None else GITHUB_REPOS

    def one(item):
        name, repo = item
        try:
            parsed = feedparser.parse(
                f"https://github.com/{repo}/releases.atom", agent=UA
            )
        except Exception:
            return []
        rows = []
        for e in parsed.entries[:10]:
            ts = _entry_ts(e)
            if ts < cutoff:
                continue
            rows.append({
                "title": f"{name} — {e.get('title', 'new release').strip()}",
                "url": e.get("link", ""),
                "discussion": "",
                "source": "Design systems",
                "points": 0,
                "comments": 0,
                "ts": ts,
                "curated": True,
                "always_relevant": True,
            })
        return rows

    with ThreadPoolExecutor(max_workers=6) as ex:
        for rows in ex.map(one, repos.items()):
            out.extend(rows)
    return out


# --------------------------------------------------------------------------
# X / Twitter, via an Apify actor. Used as a *source* of links that never
# reach Hacker News — not as a popularity signal.
# --------------------------------------------------------------------------

SOCIAL_JUNK = {
    "t.co", "x.com", "twitter.com", "pic.twitter.com", "instagram.com",
    "tiktok.com", "linkedin.com", "facebook.com", "threads.net",
    "bsky.app", "mastodon.social",
    "jobs.apple.com", "boards.greenhouse.io", "jobs.lever.co",
    "indeed.com", "glassdoor.com", "wellfound.com", "workable.com",
}


def _first(d, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _tweet_urls(tweet):
    """Pull outbound links out of a tweet, whatever shape the actor returned."""
    found = []
    ent = _first(tweet, "entities", default={}) or {}
    for u in (ent.get("urls") or []):
        if isinstance(u, dict):
            link = _first(u, "expanded_url", "unwound_url", "url")
            if link:
                found.append(link)
    for key in ("expandedUrl", "outboundLink", "link"):
        if isinstance(tweet.get(key), str):
            found.append(tweet[key])
    text = _first(tweet, "text", "full_text", "fullText", default="") or ""
    found += re.findall(r"https?://[^\s\"'<>]+", text)

    out = []
    for link in found:
        d = domain_of(link)
        if not d or d in SOCIAL_JUNK or d.endswith(".t.co"):
            continue
        out.append(link)
    return out


def _tweet_author(tweet):
    a = _first(tweet, "author", "user", default={}) or {}
    if isinstance(a, dict):
        name = _first(a, "userName", "username", "screen_name", "screenName")
        if name:
            return str(name).lower()
    return str(_first(tweet, "username", "screenName", default="") or "").lower()


def _tweet_ts(tweet):
    raw = _first(tweet, "createdAt", "created_at", "date", "timestamp")
    if isinstance(raw, (int, float)):
        return float(raw if raw < 1e12 else raw / 1000)
    if isinstance(raw, str):
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
    return time.time()


def run_apify(queries, days, max_items):
    """One batched actor run. Separate runs would multiply the start fee."""
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return None
    actor = os.environ.get("APIFY_ACTOR", APIFY_ACTOR)
    start = datetime.fromtimestamp(time.time() - days * 86400).strftime("%Y-%m-%d")
    dated = []
    for q in queries[:X_MAX_SEARCH_TERMS]:
        if "since:" not in q:
            q = f"{q} since:{start}"
        dated.append(q)
    payload = {
        "searchTerms": dated,
        "maxItems": max_items,
        "sort": "Latest",
    }
    r = HTTP.post(
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
        params={"token": token}, json=payload, timeout=300,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("items", [])


def resolve_title(url):
    """Fetch a page title for links we only saw on X. Called sparingly."""
    try:
        r = HTTP.get(url, timeout=12, allow_redirects=True,
                     headers={"Accept": "text/html"})
        r.raise_for_status()
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:200_000],
                      re.S | re.I)
        if not m:
            return None
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
        return title[:180] or None
    except Exception:
        return None


def fetch_x(days, accounts=None, verify=False):
    accounts = accounts or X_ACCOUNTS
    if not os.environ.get("APIFY_TOKEN"):
        print("x: no APIFY_TOKEN set, skipping", file=sys.stderr)
        return []

    queries = [
        " OR ".join(f"from:{h}" for h in accounts[i:i + X_ACCOUNTS_PER_QUERY])
        + " filter:links"
        for i in range(0, len(accounts), X_ACCOUNTS_PER_QUERY)
    ]
    if len(queries) > X_MAX_SEARCH_TERMS:
        kept = X_MAX_SEARCH_TERMS * X_ACCOUNTS_PER_QUERY
        print(f"x: actor allows {X_MAX_SEARCH_TERMS} queries; "
              f"using first {kept} of {len(accounts)} accounts", file=sys.stderr)
        queries = queries[:X_MAX_SEARCH_TERMS]
    try:
        tweets = run_apify(queries, days, X_MAX_TWEETS)
    except Exception as e:
        print(f"x: apify run failed ({e})", file=sys.stderr)
        return []
    if not tweets:
        print("x: actor returned nothing", file=sys.stderr)
        return []
    if len(tweets) <= X_DEMO_CAP:
        print(f"x: only {len(tweets)} tweets — Apify Free plans cap this actor "
              f"at {X_DEMO_CAP} items per run (5 runs/month). A paid plan is "
              f"needed for a real X pass.", file=sys.stderr)

    if verify:
        seen = defaultdict(int)
        for t in tweets:
            seen[_tweet_author(t)] += 1
        print("\n  account check (tweets seen in window):", file=sys.stderr)
        for h in accounts:
            n = seen.get(h.lower(), 0)
            print(f"    {'ok  ' if n else 'DEAD'} @{h}: {n}", file=sys.stderr)
        print(file=sys.stderr)

    # Group links by how many distinct accounts shared them.
    links = {}
    for t in tweets:
        author = _tweet_author(t)
        ts = _tweet_ts(t)
        engagement = (_first(t, "likeCount", "favorite_count", default=0) or 0) + \
                     (_first(t, "retweetCount", "retweet_count", default=0) or 0)
        for raw in _tweet_urls(t):
            key = canonical(raw)
            if not key:
                continue
            e = links.setdefault(key, {"url": raw, "sharers": set(),
                                       "engagement": 0, "ts": ts})
            e["sharers"].add(author)
            e["engagement"] += int(engagement)
            e["ts"] = min(e["ts"], ts)

    rows = []
    for key, e in links.items():
        authors = sorted({a.lower() for a in e["sharers"] if a})
        rows.append({
            "title": "",                       # filled in later if needed
            "url": e["url"],
            "discussion": "",
            "source": "Design X",
            "points": 0,
            "comments": 0,
            "ts": e["ts"],
            "authors": authors,
            "sharers": len(authors),
            "share_engagement": e["engagement"],
        })
    print(f"x: {len(tweets)} tweets, {len(rows)} distinct links "
          f"({sum(1 for r in rows if r['sharers'] > 1)} shared by 2+ accounts)",
          file=sys.stderr)
    return rows


def load_accounts(path):
    """Read X handles from a file, one per line. Tolerates @ and full URLs."""
    handles, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.split()[0]
            m = re.search(r"(?:x\.com/|twitter\.com/|@)?([A-Za-z0-9_]{1,15})/?$", line)
            if not m:
                continue
            h = m.group(1).lower()
            if h not in seen:
                seen.add(h)
                handles.append(h)
    return handles


def load_bsky_accounts(path):
    """Read Bluesky handles from a file. Custom domains (adactio.com) are fine."""
    handles, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.split()[0]
            line = re.sub(r"^https?://(?:www\.)?bsky\.app/profile/", "", line, flags=re.I)
            line = line.strip("/")
            if line.startswith("@"):
                line = line[1:]
            h = line.lower()
            if h and h not in seen:
                seen.add(h)
                handles.append(h)
    return handles


def substack_feed_url(raw: str) -> str:
    """Turn a slug, host, or URL into a Substack /feed address."""
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        p = urlparse(raw)
        host = p.netloc
        path = p.path.rstrip("/")
        if not path.endswith("/feed"):
            path = (path + "/feed") if path else "/feed"
        return urlunparse(("https", host, path, "", "", ""))
    host = raw.lower().lstrip("@").strip("/")
    if "." in host:
        return f"https://{host}/feed"
    return f"https://{host}.substack.com/feed"


def load_substack_pubs(path):
    """Read Substack publications from a file. Slug, host, or URL."""
    pubs, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            feed = substack_feed_url(line.split()[0])
            if feed and feed not in seen:
                seen.add(feed)
                pubs.append(feed)
    return pubs


def apply_profile_follows(profile, accounts, bsky_accounts, substack_pubs):
    """Add Taste-tab follows onto the curated watch lists. Additive."""
    people = ((profile or {}).get("seeds") or {}).get("people") or []
    x_seen = {h.lower() for h in accounts}
    bsky_seen = {h.lower() for h in bsky_accounts}
    sub_seen = set(substack_pubs)
    added = 0
    for p in people:
        if not isinstance(p, dict):
            continue
        network = (p.get("network") or "").lower()
        handle = (p.get("handle") or "").strip()
        if not handle:
            continue
        if network == "x":
            m = re.search(r"(?:x\.com/|twitter\.com/|@)?([A-Za-z0-9_]{1,15})/?$", handle)
            if not m:
                continue
            h = m.group(1).lower()
            if h not in x_seen:
                x_seen.add(h)
                accounts.append(h)
                added += 1
        elif network == "bsky":
            h = re.sub(r"^https?://(?:www\.)?bsky\.app/profile/", "", handle, flags=re.I)
            h = h.strip("/").lstrip("@").lower()
            if h and h not in bsky_seen:
                bsky_seen.add(h)
                bsky_accounts.append(h)
                added += 1
        elif network == "substack":
            feed = substack_feed_url(handle)
            if feed and feed not in sub_seen:
                sub_seen.add(feed)
                substack_pubs.append(feed)
                added += 1
    return added


def _unique_name(name, existing):
    if name not in existing:
        return name
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def apply_profile_resources(profile, curated_feeds, github_repos, substack_pubs):
    """Apply Taste-tab resources onto feeds, GitHub repos, and Substacks.

    Additive: skips a feed or repo that is already present. When the profile
    has seeds.resourcesCatalog, the caller starts from empty lists so this
    list is the watch list.
    """
    resources = ((profile or {}).get("seeds") or {}).get("resources") or []
    added = 0
    sub_seen = set(substack_pubs)
    feed_urls = set(curated_feeds.values())
    repo_vals = set(github_repos.values())
    for r in resources:
        if not isinstance(r, dict):
            continue
        kind = (r.get("kind") or "rss").lower()
        name = (r.get("name") or "").strip()
        if kind == "github":
            repo = (r.get("repo") or "").strip()
            if not repo:
                url = (r.get("url") or r.get("feed") or "")
                m = re.search(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", url, re.I)
                if m:
                    repo = m.group(1)
            repo = repo.replace(".git", "").strip("/")
            if not repo or repo in repo_vals:
                continue
            label = name or repo
            github_repos[_unique_name(label, github_repos)] = repo
            repo_vals.add(repo)
            added += 1
        elif kind == "substack":
            handle = (r.get("feed") or r.get("url") or r.get("name") or "").strip()
            if not handle:
                continue
            feed = substack_feed_url(handle)
            if not feed or feed in sub_seen:
                continue
            sub_seen.add(feed)
            substack_pubs.append(feed)
            added += 1
        else:
            feed = (r.get("feed") or r.get("url") or "").strip()
            if not feed:
                continue
            if not feed.startswith(("http://", "https://")):
                feed = "https://" + feed
            if feed in feed_urls:
                continue
            host = urlparse(feed).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            label = name or host or "Feed"
            curated_feeds[_unique_name(label, curated_feeds)] = feed
            feed_urls.add(feed)
            added += 1
    return added


def _substack_name(parsed, feed_url):
    title = (getattr(parsed, "feed", {}) or {}).get("title") or ""
    title = re.sub(r"\s*\|\s*Substack\s*$", "", title, flags=re.I).strip()
    if "|" in title:
        title = title.split("|")[0].strip()
    if title:
        return title
    host = urlparse(feed_url).netloc.lower()
    if host.endswith(".substack.com"):
        return host[: -len(".substack.com")]
    return host or "Substack"


def fetch_substack(days, pubs):
    """Public RSS from each publication. No login, free posts only."""
    if not pubs:
        print("substack: no publications listed, skipping", file=sys.stderr)
        return []
    cutoff = time.time() - days * 86400
    out = []
    live = 0

    def one(feed_url):
        try:
            parsed = feedparser.parse(feed_url, agent=UA)
        except Exception:
            return feed_url, []
        name = _substack_name(parsed, feed_url)
        rows = []
        for e in parsed.entries[:20]:
            ts = _entry_ts(e)
            if ts < cutoff:
                continue
            link = e.get("link") or ""
            if not link or not e.get("title"):
                continue
            rows.append({
                "title": e["title"].strip(),
                "url": link,
                "discussion": "",
                "source": name,
                "points": 0,
                "comments": 0,
                "ts": ts,
                "curated": True,
            })
        return feed_url, rows

    with ThreadPoolExecutor(max_workers=6) as ex:
        for feed_url, rows in ex.map(one, pubs):
            if rows:
                live += 1
            out.extend(rows)
    silent = len(pubs) - live
    print(f"substack: {live}/{len(pubs)} publications posted in window"
          f"{f' ({silent} silent or missing)' if silent else ''}",
          file=sys.stderr)
    return out


def calibrate(days, accounts, keep, max_tweets, out_path):
    """One pass over everyone you follow, ranking accounts by how much design
    they actually share. Cheaper than guessing, and it prunes on evidence."""
    if not os.environ.get("APIFY_TOKEN"):
        print("calibrate: needs APIFY_TOKEN", file=sys.stderr)
        return 1

    queries = [
        " OR ".join(f"from:{h}" for h in accounts[i:i + X_ACCOUNTS_PER_QUERY])
        + " filter:links"
        for i in range(0, len(accounts), X_ACCOUNTS_PER_QUERY)
    ]
    print(f"calibrating {len(accounts)} accounts over {len(queries)} queries, "
          f"up to {max_tweets} tweets (~${max_tweets / 1000 * 0.25:.2f})",
          file=sys.stderr)

    try:
        tweets = run_apify(queries, days, max_tweets)
    except Exception as e:
        print(f"calibrate: apify run failed ({e})", file=sys.stderr)
        return 1
    if not tweets:
        print("calibrate: actor returned nothing", file=sys.stderr)
        return 1

    stats = defaultdict(lambda: {"tweets": 0, "links": 0, "design": 0})
    for t in tweets:
        author = _tweet_author(t)
        if not author:
            continue
        s = stats[author]
        s["tweets"] += 1
        text = _first(t, "text", "full_text", "fullText", default="") or ""
        for url in _tweet_urls(t):
            s["links"] += 1
            s["design"] += lexicon_score(text, url)

    rows = []
    for h in accounts:
        s = stats.get(h, {"tweets": 0, "links": 0, "design": 0})
        # Absolute volume matters as much as purity: someone sharing eight
        # design links beats someone sharing one at 100% hit rate.
        rows.append((h, s["tweets"], s["links"], s["design"]))
    rows.sort(key=lambda r: (-r[3], -r[2], r[0]))

    print(f"\n{'handle':<22}{'tweets':>7}{'links':>7}{'design':>8}", file=sys.stderr)
    for h, tw, li, de in rows[:keep + 10]:
        mark = "  <- keep" if (h, tw, li, de) in rows[:keep] and de > 0 else ""
        print(f"@{h:<21}{tw:>7}{li:>7}{de:>8}{mark}", file=sys.stderr)

    kept = [r[0] for r in rows if r[3] > 0][:keep]
    silent = sum(1 for r in rows if r[1] == 0)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Calibrated by kerning_fetch.py --calibrate\n")
        f.write(f"# {len(kept)} kept from {len(accounts)} followed\n")
        f.write("\n".join(kept) + "\n")
    print(f"\nkept {len(kept)} of {len(accounts)} "
          f"({silent} posted nothing in the window)\nwrote {out_path}",
          file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# Bluesky — link source via public author feeds. Search is auth-only.
# --------------------------------------------------------------------------

def _iso_ts(raw):
    if not raw:
        return time.time()
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


def _bsky_post_url(post):
    handle = ((post.get("author") or {}).get("handle") or "").strip()
    uri = post.get("uri") or ""
    rkey = uri.rsplit("/", 1)[-1] if uri else ""
    if handle and rkey:
        return f"https://bsky.app/profile/{handle}/post/{rkey}"
    return ""


def _bsky_links(post):
    """Outbound http(s) links from embed cards and rich-text facets."""
    found = []
    rec = post.get("record") or {}
    embed = post.get("embed") or rec.get("embed") or {}

    def add(url, title=""):
        if not url or not str(url).startswith("http"):
            return
        d = domain_of(url)
        if not d or d in SOCIAL_JUNK or d.endswith(".t.co"):
            return
        found.append((url, (title or "").strip()))

    def walk(obj):
        if isinstance(obj, dict):
            ext = obj.get("external")
            if isinstance(ext, dict) and ext.get("uri"):
                add(ext["uri"], ext.get("title") or "")
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(embed)
    for facet in rec.get("facets") or []:
        for feat in facet.get("features") or []:
            uri = feat.get("uri")
            if uri:
                add(uri)

    seen, out = set(), []
    for url, title in found:
        key = canonical(url)
        if key and key not in seen:
            seen.add(key)
            out.append((url, title))
    return out


def _looks_like_post_text(text):
    if not text:
        return True
    if "@" in text:
        return True
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.55:
        return True
    return False


def _bsky_title(post, card_title):
    if card_title and not _looks_like_post_text(card_title):
        return card_title[:180]
    text = (post.get("record") or {}).get("text") or ""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if _looks_like_post_text(text):
        return ""
    return text[:140]


def _author_feed(actor, days):
    cutoff = time.time() - days * 86400
    posts, cursor = [], None
    for _ in range(BSKY_FEED_PAGES):
        params = {"actor": actor, "limit": 50, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        try:
            r = HTTP.get(
                "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                params=params, timeout=20,
            )
            if r.status_code in (400, 404):
                return []
            r.raise_for_status()
            data = r.json()
        except Exception:
            return posts
        page = data.get("feed") or []
        if not page:
            break
        stop = False
        for item in page:
            post = item.get("post") or {}
            rec = post.get("record") or {}
            ts = _iso_ts(rec.get("createdAt") or post.get("indexedAt"))
            if ts < cutoff:
                stop = True
                break
            posts.append((post, ts))
        if stop:
            break
        cursor = data.get("cursor")
        if not cursor:
            break
    return posts


def fetch_bluesky(days, accounts):
    """Pull links from public author feeds. Returns (rows, buzz_index).

    buzz_index maps a canonical URL to (post_count, engagement) across the
    watched accounts — a stand-in for searchPosts, which Bluesky 403s
    without a login.
    """
    if not accounts:
        print("bluesky: no accounts listed, skipping", file=sys.stderr)
        return [], {}

    def one(actor):
        return actor, _author_feed(actor, days)

    feeds = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for actor, posts in ex.map(one, accounts):
            feeds[actor] = posts

    live = sum(1 for p in feeds.values() if p)
    silent = sum(1 for a in accounts if not feeds.get(a))
    print(f"bluesky: {live}/{len(accounts)} accounts posted in window"
          f"{f' ({silent} silent or missing)' if silent else ''}",
          file=sys.stderr)

    links = {}
    n_posts_with_links = 0
    for actor, posts in feeds.items():
        for post, ts in posts:
            urls = _bsky_links(post)
            if not urls:
                continue
            n_posts_with_links += 1
            engagement = (
                (post.get("likeCount") or 0)
                + (post.get("repostCount") or 0)
                + (post.get("replyCount") or 0)
            )
            discussion = _bsky_post_url(post)
            for raw, card_title in urls:
                key = canonical(raw)
                if not key:
                    continue
                e = links.setdefault(key, {
                    "url": raw,
                    "title": "",
                    "sharers": set(),
                    "engagement": 0,
                    "posts": 0,
                    "ts": ts,
                    "discussion": discussion,
                })
                e["sharers"].add(actor.lower())
                e["engagement"] += int(engagement)
                e["posts"] += 1
                e["ts"] = min(e["ts"], ts)
                title = _bsky_title(post, card_title)
                if len(title) > len(e["title"]) and len(title) < 140:
                    e["title"] = title
                if not e["discussion"] and discussion:
                    e["discussion"] = discussion

    rows, buzz = [], {}
    for key, e in links.items():
        buzz[key] = (e["posts"], e["engagement"])
        authors = sorted({a.lower() for a in e["sharers"] if a})
        rows.append({
            "title": e["title"],
            "url": e["url"],
            "discussion": e["discussion"],
            "source": "Bluesky",
            "points": 0,
            "comments": 0,
            "ts": e["ts"],
            "authors": authors,
            "sharers": len(authors),
            "share_engagement": e["engagement"],
        })
    multi = sum(1 for r in rows if r["sharers"] > 1)
    print(f"bluesky: {n_posts_with_links} posts with links, {len(rows)} distinct"
          f" ({multi} shared by 2+ accounts)", file=sys.stderr)
    return rows, buzz


class BlueskySearch:
    """Optional searchPosts overlay. Requires an app password — anonymous
    search is refused at the CDN (403)."""

    def __init__(self):
        self.headers = {}
        self.ok = False
        handle = os.environ.get("BSKY_HANDLE")
        password = os.environ.get("BSKY_APP_PASSWORD")
        if not (handle and password):
            return
        try:
            r = HTTP.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": handle, "password": password}, timeout=20,
            )
            r.raise_for_status()
            self.headers = {"Authorization": "Bearer " + r.json()["accessJwt"]}
            self.ok = True
            print("  bluesky: search authenticated", file=sys.stderr)
        except Exception as e:
            print(f"  bluesky: auth failed ({e}); feed buzz only", file=sys.stderr)

    def buzz(self, title: str):
        if not self.ok:
            return 0, 0
        phrase = " ".join(re.findall(r"[A-Za-z0-9']+", title)[:8])
        if len(phrase) < 12:
            return 0, 0
        try:
            r = HTTP.get(
                "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
                params={"q": phrase, "limit": 25, "sort": "latest"},
                headers=self.headers, timeout=15,
            )
            if r.status_code in (401, 403):
                self.ok = False
                print("  bluesky: authenticated search refused, "
                      "sticking with feed buzz", file=sys.stderr)
                return 0, 0
            r.raise_for_status()
            posts = r.json().get("posts", [])
        except Exception:
            return 0, 0
        engagement = sum(
            (p.get("likeCount") or 0) + (p.get("repostCount") or 0)
            + (p.get("replyCount") or 0)
            for p in posts
        )
        return len(posts), engagement


# --------------------------------------------------------------------------
# Merge, score, cut
# --------------------------------------------------------------------------

def _author_list(row):
    out, seen = [], set()
    for a in row.get("authors") or []:
        if not a:
            continue
        k = str(a).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def merge(rows):
    """Collapse rows sharing a canonical URL, keeping the best of each field."""
    merged = {}
    for r in rows:
        key = canonical(r["url"])
        if not key:
            continue
        authors = _author_list(r)
        m = merged.get(key)
        if m is None:
            merged[key] = {
                "key": key,
                "title": r["title"],
                "url": r["url"],
                "discussion": r.get("discussion", ""),
                "sources": [r["source"]],
                "points": r["points"],
                "comments": r["comments"],
                "ts": r["ts"],
                "curated": r.get("curated", False),
                "always_relevant": r.get("always_relevant", False),
                "authors": authors,
                "sharers": r.get("sharers", 0),
                "share_engagement": r.get("share_engagement", 0),
            }
            continue
        if r["source"] not in m["sources"]:
            m["sources"].append(r["source"])
        m["points"] = max(m["points"], r["points"])
        m["comments"] = max(m["comments"], r["comments"])
        m["ts"] = min(m["ts"], r["ts"])          # earliest sighting
        m["curated"] = m["curated"] or r.get("curated", False)
        m["always_relevant"] = m["always_relevant"] or r.get("always_relevant", False)
        m["sharers"] = m["sharers"] + r.get("sharers", 0)
        m["share_engagement"] = m["share_engagement"] + r.get("share_engagement", 0)
        seen = {a.lower() for a in m.get("authors") or []}
        for a in authors:
            if a not in seen:
                seen.add(a)
                m["authors"].append(a)
        if not m["discussion"] and r.get("discussion"):
            m["discussion"] = r["discussion"]
        if len(r["title"]) > len(m["title"]) and len(r["title"]) < 140:
            m["title"] = r["title"]
    return list(merged.values())


def score(item, weights, now, recency_tau=7, skip_urls=None):
    rel = 0 if item["always_relevant"] else lexicon_score(item["title"], item["url"])
    if item["always_relevant"]:
        rel = 6

    n_src = len(item["sources"])
    sharers = item.get("sharers", 0)
    corroboration = (math.log2(n_src) if n_src > 1 else 0.0)
    if sharers > 1:
        corroboration += math.log2(sharers) * 0.8
    attention = math.log10(1 + item["points"])
    debate = min(item["comments"] / max(item["points"], 8), 1.5)
    posts, engagement = item.get("_buzz", (0, 0))
    buzz = math.log10(1 + posts) + math.log10(1 + engagement) * 0.4
    curation = 1.0 if item["curated"] else 0.0
    authors = item.get("authors") or []
    taste = taste_score(item["title"], item["url"], weights, authors)
    age_days = max((now - item["ts"]) / 86400, 0)
    recency = math.exp(-age_days / recency_tau)

    total = (
        W["corroboration"] * corroboration
        + W["relevance"] * min(rel, 8) / 3
        + W["attention"] * attention
        + W["debate"] * debate
        + W["buzz"] * buzz
        + W["curation"] * curation
        + W["taste"] * taste
        + W["recency"] * recency
    )
    if skip_urls and item.get("key") in skip_urls:
        total -= 50

    why = []
    if n_src > 1:
        why.append(f"picked up by {' and '.join(item['sources'])}")
    if sharers > 1:
        why.append(f"shared by {sharers} design accounts")
    elif sharers == 1 and n_src == 1:
        src0 = item["sources"][0]
        if src0 == "Bluesky":
            why.append("spotted on Bluesky")
        elif src0 == "Design X":
            why.append("spotted on design X")
    if posts >= 2:
        why.append(f"{posts} Bluesky posts")
    if item["points"] >= 150:
        why.append(f"{item['points']} points")
    if debate >= 0.7 and item["comments"] >= 25:
        why.append(f"heavily argued ({item['comments']} comments)")
    if curation and n_src == 1:
        why.append(f"editor's pick at {item['sources'][0]}")
    followed = [
        a for a in authors
        if weights.get(f"person:{str(a).lower()}", 0) > 0
    ]
    if followed:
        why.append("from someone you follow")
    if taste >= 0.6:
        why.append("matches your profile")

    item["score"] = round(total, 3)
    item["relevance"] = rel
    item["why"] = why
    return item


def diversify(items, limit):
    """Keep the list varied so one blog or aggregator can't fill the digest."""
    per_domain, per_source, kept = defaultdict(int), defaultdict(int), []
    for it in items:
        d = domain_of(it["url"])
        s = it["sources"][0]
        if per_domain[d] >= MAX_PER_DOMAIN or per_source[s] >= MAX_PER_SOURCE:
            continue
        per_domain[d] += 1
        per_source[s] += 1
        kept.append(it)
        if len(kept) >= limit:
            break
    return kept


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def serialize_item(it):
    out = {
        "id": hashlib.sha1(it["key"].encode()).hexdigest()[:12],
        "title": it["title"],
        "url": it["url"],
        "hn": it["discussion"] or it["url"],
        "points": it["points"],
        "comments": it["comments"],
        "created_at_i": int(it["ts"]),
        "sources": it["sources"],
        "sharers": it.get("sharers", 0),
        "score": it["score"],
        "why": it["why"],
    }
    authors = [a for a in (it.get("authors") or []) if a][:8]
    if authors:
        out["authors"] = authors
    return out


def cut_edition(items, since, limit, weights, now, recency_tau, skip_urls=None):
    skip_urls = skip_urls or set()
    pool = [
        dict(it) for it in items
        if it["ts"] >= since and it.get("key") not in skip_urls
    ]
    ranked = sorted(
        (score(it, weights, now, recency_tau, skip_urls) for it in pool),
        key=lambda x: x["score"],
        reverse=True,
    )
    return diversify(ranked, limit)


def write_json(path, cadences, generated_at=None):
    weekly = cadences.get("weekly") or next(iter(cadences.values()), {})
    payload = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "cadence": "weekly" if "weekly" in cadences else next(iter(cadences), "weekly"),
        "window_days": 7,
        "cadences": cadences,
        "items": weekly.get("items", []),
    }
    for key in ("week_start", "week_end", "week_label", "iso_week"):
        if key in weekly:
            payload[key] = weekly[key]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _md_items(items):
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"**{i}. [{it['title']}]({it['url']})**")
        bits = [domain_of(it["url"])]
        if it.get("why"):
            bits.append("; ".join(it["why"]))
        lines.append("  " + " — ".join(b for b in bits if b))
        if it.get("discussion") and it["discussion"] != it["url"]:
            lines.append(f"  [Discussion]({it['discussion']})")
        elif it.get("hn") and it["hn"] != it["url"]:
            lines.append(f"  [Discussion]({it['hn']})")
        lines.append("")
    return lines


def write_markdown(path, cadences):
    order = [k for k in ("daily", "weekly", "monthly") if k in cadences]
    if not order:
        order = list(cadences)
    lines = ["# Kerning", ""]
    blurbs = {
        "daily": "Today",
        "weekly": "This week",
        "monthly": "This month",
    }
    for kind in order:
        pack = cadences[kind]
        label = pack.get("label") or kind
        items = pack.get("items") or []
        lines.append(f"## {blurbs.get(kind, kind)} — {label}")
        lines.append("")
        lines.append(f"The {len(items)} best design and product reads.")
        lines.append("")
        lines.extend(_md_items(items))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Build daily, weekly, and monthly design and product digests.")
    ap.add_argument("--days", type=int, default=None,
                    help="rolling window in days (default: this calendar week)")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--profile", default="kerning-profile.json",
                    help="taste profile exported from the Kerning web app")
    ap.add_argument("--out", default="digest")
    ap.add_argument("--no-buzz", action="store_true",
                    help="skip authenticated Bluesky search (feed buzz still applies)")
    ap.add_argument("--no-x", action="store_true",
                    help="skip the Apify X source even if APIFY_TOKEN is set")
    ap.add_argument("--no-bluesky", action="store_true",
                    help="skip the Bluesky author-feed source")
    ap.add_argument("--no-substack", action="store_true",
                    help="skip Substack publication feeds")
    ap.add_argument("--substack", default="substack.txt",
                    help="file of Substack publications, one per line")
    ap.add_argument("--verify-accounts", action="store_true",
                    help="report which X handles actually returned tweets")
    ap.add_argument("--accounts", default="accounts.txt",
                    help="file of X handles, one per line")
    ap.add_argument("--bsky-accounts", default="bsky-accounts.txt",
                    help="file of Bluesky handles, one per line")
    ap.add_argument("--calibrate", metavar="FILE",
                    help="rank the handles in FILE by how much design they "
                         "share, then write a pruned list to --accounts")
    ap.add_argument("--keep", type=int, default=40,
                    help="how many accounts to keep when calibrating")
    ap.add_argument("--calibrate-tweets", type=int, default=3000,
                    help="tweet budget for the calibration run")
    args = ap.parse_args()

    if args.calibrate:
        everyone = load_accounts(args.calibrate)
        if not everyone:
            print(f"no handles found in {args.calibrate}", file=sys.stderr)
            return 1
        return calibrate(args.days or 7, everyone, args.keep,
                         args.calibrate_tweets, args.accounts)

    if os.path.exists(args.accounts):
        accounts = load_accounts(args.accounts)
        print(f"x accounts: {len(accounts)} from {args.accounts}", file=sys.stderr)
    else:
        accounts = X_ACCOUNTS

    if os.path.exists(args.bsky_accounts):
        bsky_accounts = load_bsky_accounts(args.bsky_accounts)
        print(f"bluesky accounts: {len(bsky_accounts)} from {args.bsky_accounts}",
              file=sys.stderr)
    else:
        bsky_accounts = []

    weights = {}
    profile_data = {}
    profile_ok = False
    if os.path.exists(args.profile):
        try:
            profile_data = json.load(open(args.profile))
            weights = profile_data.get("weights") or {}
            profile_ok = True
        except Exception:
            print("taste profile: unreadable, ignoring", file=sys.stderr)

    catalog = bool(((profile_data or {}).get("seeds") or {}).get("resourcesCatalog"))
    if catalog:
        substack_pubs = []
        print("taste catalog: watching only resources from the profile",
              file=sys.stderr)
    elif os.path.exists(args.substack):
        substack_pubs = load_substack_pubs(args.substack)
        print(f"substack: {len(substack_pubs)} from {args.substack}", file=sys.stderr)
    else:
        substack_pubs = []

    n_follows = apply_profile_follows(
        profile_data, accounts, bsky_accounts, substack_pubs,
    )
    feeds = {} if catalog else dict(CURATED_FEEDS)
    repos = {} if catalog else dict(GITHUB_REPOS)
    n_resources = apply_profile_resources(
        profile_data, feeds, repos, substack_pubs,
    )
    skip_urls = downvoted_urls(profile_data)
    if profile_ok:
        extra = []
        if n_follows:
            extra.append(f"+{n_follows} follows")
        if n_resources:
            extra.append(f"+{n_resources} resources")
        if skip_urls:
            extra.append(f"skipping {len(skip_urls)} downvoted urls")
        suffix = (", " + ", ".join(extra)) if extra else ""
        print(f"taste profile: {len(weights)} learned terms{suffix}", file=sys.stderr)

    now_dt = datetime.now().astimezone()
    day_start, day_end = this_day(now_dt)
    week_start, week_end = this_week(now_dt)
    month_start, month_end = this_month(now_dt)

    if args.days is not None:
        days = float(args.days)
        periods = {
            "weekly": (now_dt - timedelta(days=days), now_dt + timedelta(seconds=1)),
        }
        print(f"window: last {args.days} days", file=sys.stderr)
    else:
        days = max((time.time() - month_start.timestamp()) / 86400, 1 / 24)
        periods = {
            "daily": (day_start, day_end),
            "weekly": (week_start, week_end),
            "monthly": (month_start, month_end),
        }
        print(f"day: {day_start.strftime('%d %B')}", file=sys.stderr)
        print(f"week: {week_label(week_start, week_end)} ({iso_week_id(week_start)})",
              file=sys.stderr)
        print(f"month: {month_start.strftime('%B %Y')}", file=sys.stderr)

    rows = []
    bsky_buzz = {}
    for label, fn in (("hacker news", fetch_hn), ("lobsters", fetch_lobsters)):
        try:
            got = fn(days)
            rows.extend(got)
            print(f"{label}: {len(got)}", file=sys.stderr)
        except Exception as e:
            print(f"{label}: failed ({e})", file=sys.stderr)
    for label, fn, arg in (
        ("publications", fetch_feeds, feeds),
        ("design systems", fetch_releases, repos),
    ):
        try:
            got = fn(days, arg)
            rows.extend(got)
            print(f"{label}: {len(got)}", file=sys.stderr)
        except Exception as e:
            print(f"{label}: failed ({e})", file=sys.stderr)

    if not args.no_x:
        try:
            rows.extend(fetch_x(days, accounts=accounts,
                                verify=args.verify_accounts))
        except Exception as e:
            print(f"x: failed ({e})", file=sys.stderr)

    if not args.no_bluesky:
        try:
            got, bsky_buzz = fetch_bluesky(days, bsky_accounts)
            rows.extend(got)
        except Exception as e:
            print(f"bluesky: failed ({e})", file=sys.stderr)

    if not args.no_substack:
        try:
            got = fetch_substack(days, substack_pubs)
            rows.extend(got)
            print(f"substack: {len(got)} posts", file=sys.stderr)
        except Exception as e:
            print(f"substack: failed ({e})", file=sys.stderr)

    if not rows:
        print("nothing fetched — check your connection", file=sys.stderr)
        return 1

    items = merge(rows)
    print(f"merged: {len(items)} unique links "
          f"({sum(1 for i in items if len(i['sources']) > 1)} seen in 2+ places)",
          file=sys.stderr)

    # Links only social sources had arrive without a title. Fetch one, but
    # only for links more than one account bothered to share.
    untitled = [i for i in items if not i["title"]]
    min_sharers = min(X_MIN_SHARERS_FOR_LOOKUP, BSKY_MIN_SHARERS_FOR_LOOKUP)
    chase = [i for i in untitled
             if i["sharers"] >= min_sharers or "Bluesky" in i["sources"]]
    if chase:
        print(f"resolving {len(chase)} titles from social-only links "
              f"(skipping {len(untitled) - len(chase)} single-share)", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=6) as ex:
            for it, title in zip(chase, ex.map(lambda i: resolve_title(i["url"]), chase)):
                it["title"] = title or ""
    items = [i for i in items if i["title"]]

    now = time.time()
    items = [i for i in items
             if i["always_relevant"] or lexicon_score(i["title"], i["url"]) >= 2]
    if skip_urls:
        items = [i for i in items if i.get("key") not in skip_urls]

    short_tau = RECENCY_TAU["monthly"] if args.days is None else 7
    shortlist = sorted(
        items,
        key=lambda i: score(i, weights, now, short_tau, skip_urls)["score"],
        reverse=True,
    )[:SHORTLIST]

    searcher = None if args.no_buzz else BlueskySearch()
    for it in shortlist:
        feed = bsky_buzz.get(it["key"], (0, 0))
        extra = (0, 0)
        if searcher and searcher.ok:
            extra = searcher.buzz(it["title"])
            time.sleep(0.3)
        it["_buzz"] = (feed[0] + extra[0], feed[1] + extra[1])
    buzz_by_key = {it["key"]: it["_buzz"] for it in shortlist}
    for it in items:
        it["_buzz"] = buzz_by_key.get(it["key"]) or bsky_buzz.get(it["key"], (0, 0))
    got = sum(1 for it in shortlist if it["_buzz"][0])
    print(f"bluesky: buzz found for {got}/{len(shortlist)}", file=sys.stderr)

    generated_at = datetime.now(timezone.utc).isoformat()
    cadences = {}
    for kind, (start, end) in periods.items():
        tau = RECENCY_TAU.get(kind, 7)
        picked = cut_edition(
            items, start.timestamp(), args.limit, weights, now, tau, skip_urls,
        )
        pack = edition_meta(kind, start, end)
        pack["items"] = [serialize_item(it) for it in picked]
        cadences[kind] = pack
        print(f"{kind}: {len(picked)} items", file=sys.stderr)

    write_json(args.out + ".json", cadences, generated_at)
    write_markdown(args.out + ".md", cadences)
    print(f"\nwrote {args.out}.json and {args.out}.md — "
          + ", ".join(f"{k} {len(cadences[k]['items'])}" for k in cadences),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
