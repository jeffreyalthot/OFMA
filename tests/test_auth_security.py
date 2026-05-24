import shutil
import tempfile
import unittest
from pathlib import Path

import elit21.db as db
from elit21.web.app import create_app, verify_password


class AuthSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="ofma-auth-")
        db.DB_PATH = Path(self._tmpdir) / "test.db"
        db.UPLOADS_PATH = Path(self._tmpdir) / "uploads"
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_register_stores_strong_hash(self):
        response = self.client.post(
            "/register",
            data={
                "email": "user@example.com",
                "full_name": "Demo User",
                "password": "StrongPass123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("user@example.com",),
            ).fetchone()
        self.assertIsNotNone(row)
        stored = str(row["password_hash"])
        self.assertNotEqual(len(stored), 64)
        self.assertTrue(stored.startswith("scrypt:") or stored.startswith("pbkdf2:"))

    def test_verify_password_accepts_legacy_sha256_hash(self):
        legacy_hash = "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4"
        self.assertTrue(verify_password("1234", legacy_hash))
        self.assertFalse(verify_password("wrong", legacy_hash))

    def test_security_headers_present(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'self'", response.headers.get("Content-Security-Policy", ""))

    def test_login_rate_limit_blocks_after_retries(self):
        self.client.post(
            "/register",
            data={
                "email": "ratelimit@example.com",
                "full_name": "Rate Limit User",
                "password": "CorrectPass123!",
            },
            follow_redirects=False,
        )
        for _ in range(5):
            response = self.client.post(
                "/login",
                data={"email": "ratelimit@example.com", "password": "wrong"},
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        blocked_response = self.client.post(
            "/login",
            data={"email": "ratelimit@example.com", "password": "wrong"},
            follow_redirects=True,
        )
        self.assertEqual(blocked_response.status_code, 200)
        self.assertIn("Trop de tentatives", blocked_response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
