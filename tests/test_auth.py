import os
import unittest

from kerning_lib.auth import cron_authorized


class CronAuthTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.get("CRON_SECRET")

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("CRON_SECRET", None)
        else:
            os.environ["CRON_SECRET"] = self.previous

    def test_bearer_must_match(self):
        os.environ["CRON_SECRET"] = "s3cret"
        self.assertTrue(cron_authorized({"Authorization": "Bearer s3cret"}))
        self.assertTrue(cron_authorized({"authorization": "Bearer s3cret"}))
        self.assertFalse(cron_authorized({"Authorization": "Bearer other"}))
        self.assertFalse(cron_authorized({"Authorization": "s3cret"}))
        self.assertFalse(cron_authorized({}))

    def test_missing_secret_denies(self):
        os.environ.pop("CRON_SECRET", None)
        self.assertFalse(cron_authorized({"Authorization": "Bearer s3cret"}))
