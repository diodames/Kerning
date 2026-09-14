import unittest

from kerning_lib.rebuild import API_REBUILD_TRY_LOCAL, after_api_rebuild


class RebuildStatusTests(unittest.TestCase):
    def test_ok_and_poll(self):
        self.assertEqual(after_api_rebuild(200), "ok")
        self.assertEqual(after_api_rebuild(202), "poll")

    def test_try_local_for_missing_or_static_server(self):
        for status in (403, 404, 405, 501):
            self.assertEqual(after_api_rebuild(status), "try_local", status)
        self.assertEqual(API_REBUILD_TRY_LOCAL, frozenset((403, 404, 405, 501)))

    def test_other_statuses_are_errors(self):
        self.assertEqual(after_api_rebuild(500), "error")
        self.assertEqual(after_api_rebuild(429), "error")


if __name__ == "__main__":
    unittest.main()
