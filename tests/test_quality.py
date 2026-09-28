import unittest

from kerning_lib.quality import github_release_verdict, marketing_weight, quality_reason


CFG = {
    "hn": {"min_points": 10, "min_comments": 5},
    "lobsters": {"min_score": 3},
    "blocklist": ["spam.example"],
    "allowlist": ["good.example"],
    "saas_domains": {"linear.app": ["linear"]},
    "saas_weight": 0.35,
    "saas_low_points": 20,
}


def _item(**kwargs):
    row = {
        "title": "A design system",
        "url": "https://news.ycombinator.com/item?id=1",
        "sources": ["Hacker News"],
        "points": 3,
        "comments": 0,
        "curated": False,
    }
    row.update(kwargs)
    return row


class QualityTests(unittest.TestCase):
    def test_hn_below_threshold(self):
        self.assertEqual(quality_reason(_item(), CFG), "below_threshold")
        self.assertIsNone(quality_reason(_item(points=12), CFG))
        self.assertIsNone(quality_reason(_item(points=3, comments=8), CFG))

    def test_blocklist(self):
        self.assertEqual(
            quality_reason(_item(url="https://spam.example/post", points=99), CFG),
            "blocklist",
        )

    def test_prerelease_dropped(self):
        self.assertEqual(
            github_release_verdict("Primer — v2.1.0-rc.3"),
            "prerelease",
        )
        self.assertEqual(
            github_release_verdict("Radix — 1.4.0-beta.1"),
            "prerelease",
        )
        self.assertIsNone(github_release_verdict("Primer — v2.1.0"))

    def test_patch_without_breaking_dropped(self):
        self.assertEqual(
            github_release_verdict("Carbon — v1.2.3"),
            "patch",
        )
        self.assertIsNone(github_release_verdict("Carbon — v1.2.3 breaking change"))
        self.assertIsNone(github_release_verdict("Carbon — v2.0.0"))

    def test_github_item_uses_verdict(self):
        item = _item(
            sources=["Design systems"],
            title="Primer — v1.8.4",
            url="https://github.com/primer/react/releases/tag/v1.8.4",
            points=0,
        )
        self.assertEqual(quality_reason(item, CFG), "patch")

    def test_saas_downweight_not_drop(self):
        item = _item(
            url="https://linear.app/blog/linear-ai",
            title="Linear AI is here",
            points=4,
            comments=0,
            sources=["Hacker News"],
        )
        self.assertEqual(quality_reason(item, CFG), "below_threshold")
        item["points"] = 12
        self.assertIsNone(quality_reason(item, CFG))
        self.assertEqual(marketing_weight(item, CFG), 0.35)
        item["points"] = 40
        self.assertEqual(marketing_weight(item, CFG), 1.0)

    def test_allowlist_skips_marketing_heuristic(self):
        item = _item(
            url="https://good.example/linear-launch",
            title="Linear thoughts",
            points=12,
        )
        self.assertEqual(marketing_weight(item, CFG), 1.0)

    def test_lobsters_below_score(self):
        item = _item(sources=["Lobsters"], points=2, url="https://lobste.rs/s/abc")
        self.assertEqual(quality_reason(item, CFG), "below_threshold")
        item["points"] = 3
        self.assertIsNone(quality_reason(item, CFG))
