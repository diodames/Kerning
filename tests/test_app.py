import os
import tempfile
import unittest
from urllib.parse import urlparse

_DB = os.path.join(tempfile.mkdtemp(), "kerning-test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _DB
os.environ["APP_ORIGIN"] = "http://127.0.0.1:8000"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["RESEND_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.config import is_dev_origin  # noqa: E402
from app.crawl import pool_is_fresh, pool_items, upsert_rows  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_dev_link_only_on_loopback(self):
        self.assertTrue(is_dev_origin("http://127.0.0.1:8000"))
        self.assertTrue(is_dev_origin("http://localhost:8000"))
        self.assertFalse(is_dev_origin("https://kerning.fly.dev"))
        r = self.client.post(
            "/auth/request",
            json={"email": "devlink@example.com"},
        )
        self.assertIn("devLink", r.json())

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)

    def test_me_requires_session(self):
        r = TestClient(app).get("/me")
        self.assertEqual(r.status_code, 401)

    def test_magic_link_profile_and_digest_404(self):
        r = self.client.post(
            "/auth/request",
            json={"email": "ada@example.com", "timezone": "Europe/Prague"},
        )
        self.assertEqual(r.status_code, 200)
        link = r.json().get("devLink")
        self.assertTrue(link)
        parsed = urlparse(link)
        path = parsed.path + "?" + parsed.query
        r = self.client.get(path, follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        r = self.client.get("/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["email"], "ada@example.com")
        r = self.client.put("/me/profile", json={
            "weights": {"figma": 1},
            "ratings": {},
            "saved": [],
            "seeds": {"people": [], "articles": [], "resources": []},
        })
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/me/profile")
        self.assertEqual(r.json()["weights"]["figma"], 1)
        r = self.client.get("/me/digest")
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/me/rebuild")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("jobId"))

    def test_upsert_pool(self):
        db = SessionLocal()
        try:
            n = upsert_rows(db, [{
                "title": "A design system",
                "url": "https://example.com/ds",
                "source": "Hacker News",
                "points": 10,
                "comments": 1,
                "ts": 1700000000,
            }])
            self.assertTrue(n)
            self.assertTrue(pool_is_fresh(db))
            rows = pool_items(db, "user-1", since_ts=0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "https://example.com/ds")
            self.assertEqual(rows[0]["source"], "Hacker News")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
