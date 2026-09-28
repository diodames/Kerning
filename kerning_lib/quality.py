"""Quality gate for the daily close. Collection does not use this."""

import json
import os
import re

from kerning_fetch import domain_of

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_HERE, "quality.json")

PRE_RELEASE = re.compile(
    r"\b(rc|beta|alpha|canary|pre-release|prerelease)\d*\b", re.I
)
SEMVER = re.compile(r"\bv?(\d+)\.(\d+)\.(\d+)\b")
BREAKING = re.compile(r"\bbreaking\b", re.I)


def load_quality(path=None):
    with open(path or _CONFIG_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {}
    return data


def source_kind(item):
    sources = item.get("sources") or []
    if "Hacker News" in sources:
        return "hn"
    if "Lobsters" in sources:
        return "lobsters"
    if "Design systems" in sources:
        return "github"
    return "other"


def github_release_verdict(title, notes=""):
    """Drop pre-releases and patches without a breaking note. Else None."""
    hay = "%s %s" % (title or "", notes or "")
    if PRE_RELEASE.search(hay):
        return "prerelease"
    match = SEMVER.search(title or "")
    if not match:
        return None
    patch = int(match.group(3))
    major = int(match.group(1))
    if patch != 0 and major > 0 and not BREAKING.search(hay):
        return "patch"
    return None


def quality_reason(item, cfg=None):
    """Return a drop reason, or None if the item may be ranked."""
    cfg = cfg if cfg is not None else load_quality()
    title = (item.get("title") or "").strip()
    if not title:
        return "no_title"
    domain = domain_of(item.get("url") or "")
    blocklist = set(cfg.get("blocklist") or [])
    if domain in blocklist:
        return "blocklist"
    kind = source_kind(item)
    if kind == "github":
        verdict = github_release_verdict(title)
        if verdict:
            return verdict
    if kind == "hn":
        hn = cfg.get("hn") or {}
        min_points = int(hn.get("min_points") or 0)
        min_comments = int(hn.get("min_comments") or 0)
        points = int(item.get("points") or 0)
        comments = int(item.get("comments") or 0)
        if points < min_points and comments < min_comments:
            return "below_threshold"
    if kind == "lobsters":
        lo = cfg.get("lobsters") or {}
        min_score = int(lo.get("min_score") or 0)
        if int(item.get("points") or 0) < min_score:
            return "below_threshold"
    return None


def marketing_weight(item, cfg=None):
    """Downweight SaaS content marketing; never drop. 1.0 means unchanged."""
    cfg = cfg if cfg is not None else load_quality()
    if item.get("curated"):
        return 1.0
    domain = domain_of(item.get("url") or "")
    allowlist = set(cfg.get("allowlist") or [])
    if domain in allowlist:
        return 1.0
    brands = cfg.get("saas_domains") or {}
    tokens = brands.get(domain) or []
    if not tokens:
        return 1.0
    title = (item.get("title") or "").lower()
    if not any(str(t).lower() in title for t in tokens):
        return 1.0
    low = int(cfg.get("saas_low_points") or 20)
    if int(item.get("points") or 0) >= low:
        return 1.0
    return float(cfg.get("saas_weight") or 0.35)
