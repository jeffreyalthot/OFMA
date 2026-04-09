import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import elit21.db as db
from elit21.web.app import create_app


class ApiProductsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="ofma-api-")
        db.DB_PATH = Path(self._tmpdir) / "test.db"
        db.UPLOADS_PATH = Path(self._tmpdir) / "uploads"
        self.app = create_app()
        self.client = self.app.test_client()

        with db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO products (name, description, price, status, stock, color, size, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Manteau Hiver",
                    "Manteau premium",
                    149.99,
                    "active",
                    12,
                    "Noir",
                    "M",
                    "Vestes",
                    datetime.utcnow().isoformat(),
                ),
            )
            self.product_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            conn.execute(
                """
                INSERT INTO product_images (product_id, image_blob, image_path, mime_type, position)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self.product_id, None, "uploads/products/demo.jpg", "image/jpeg", 1),
            )
            conn.execute(
                """
                INSERT INTO product_inventory (product_id, color, size, quantity)
                VALUES (?, ?, ?, ?)
                """,
                (self.product_id, "Noir", "M", 5),
            )
            conn.commit()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_api_products_returns_active_products(self):
        response = self.client.get("/api/products")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["products"][0]["id"], self.product_id)
        self.assertIn(f"/product/{self.product_id}/image/", payload["products"][0]["image_url"])

    def test_api_products_limit_requires_integer(self):
        response = self.client.get("/api/products?limit=abc")
        self.assertEqual(response.status_code, 400)

    def test_api_product_detail_includes_inventory(self):
        response = self.client.get(f"/api/products/{self.product_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["id"], self.product_id)
        self.assertEqual(payload["inventory"][0]["quantity"], 5)

    def test_malformed_cart_key_does_not_break_cart_page(self):
        with self.client.session_transaction() as sess:
            sess["cart"] = {"invalid-key": 3}

        response = self.client.get("/cart")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
