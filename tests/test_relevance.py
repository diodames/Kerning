import time
import unittest

import kerning_fetch as kf


def _item(**kwargs):
    now = kwargs.pop("now", time.time())
    row = {
        "title": "Untitled",
        "url": "https://example.com/p",
        "sources": ["Hacker News"],
        "points": 0,
        "comments": 0,
        "ts": now - 3600,
        "curated": False,
        "always_relevant": False,
        "authors": [],
        "sharers": 0,
        "share_engagement": 0,
    }
    row.update(kwargs)
    return row


class RelevanceTests(unittest.TestCase):
    def test_curated_essay_passes_without_design_words(self):
        item = _item(
            title="AI and the Future of the Product Role",
            url="https://www.svpg.com/ai-and-the-future-of-the-product-role/",
            sources=["SVPG"],
            curated=True,
        )
        self.assertTrue(kf.relevant_enough(item))

    def test_uncurated_offtopic_fails(self):
        item = _item(title="Earnings beat estimates", url="https://markets.example/a")
        self.assertFalse(kf.relevant_enough(item))

    def test_github_release_still_passes_the_gate(self):
        item = _item(
            title="Primer (GitHub) — @primer/react@38.44.0",
            url="https://github.com/primer/react/releases/tag/@primer/react@38.44.0",
            sources=["Design systems"],
            curated=True,
            always_relevant=True,
        )
        self.assertTrue(kf.relevant_enough(item))

    def test_releases_do_not_get_a_fake_lexicon_score(self):
        now = time.time()
        gh = scoreable_release(now)
        scored = kf.score(gh, {}, now)
        self.assertEqual(scored["relevance"], 0)

    def test_svpg_essay_outranks_a_github_release(self):
        now = time.time()
        svpg = _item(
            title="AI and the Future of the Product Role",
            url="https://www.svpg.com/ai-and-the-future-of-the-product-role/",
            sources=["SVPG"],
            curated=True,
            ts=now - 3600,
        )
        gh = scoreable_release(now)
        self.assertGreater(
            kf.score(svpg, {}, now)["score"],
            kf.score(gh, {}, now)["score"],
        )

    def test_svpg_rss_outranks_ux_collective_rss(self):
        now = time.time()
        svpg = _item(
            title="AI and the Future of the Product Role",
            url="https://www.svpg.com/ai-and-the-future-of-the-product-role/",
            sources=["SVPG"],
            curated=True,
            ts=now - 2 * 86400,
        )
        ux = _item(
            title="How we save entry-level UX work",
            url="https://uxdesign.cc/how-we-save-entry-level-ux-work",
            sources=["UX Collective"],
            curated=True,
            ts=now - 2 * 86400,
        )
        self.assertGreater(
            kf.score(svpg, {}, now)["score"],
            kf.score(ux, {}, now)["score"],
        )

    def test_ux_collective_keeps_full_curation_when_also_on_hn(self):
        item = _item(
            title="How we save entry-level UX work",
            url="https://uxdesign.cc/how-we-save-entry-level-ux-work",
            sources=["Hacker News", "UX Collective"],
            curated=True,
        )
        self.assertEqual(kf.curation_strength(item), 1.0)


def scoreable_release(now):
    return _item(
        title="Primer (GitHub) — @primer/react@38.44.0",
        url="https://github.com/primer/react/releases/tag/@primer/react@38.44.0",
        sources=["Design systems"],
        curated=True,
        always_relevant=True,
        ts=now - 3600,
        now=now,
    )
