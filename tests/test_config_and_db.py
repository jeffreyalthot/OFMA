import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import elit21.db as db
from elit21.config import DEFAULT_SECRET, load_app_config


class ConfigAndDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="ofma-config-db-")
        db.DB_PATH = Path(self._tmpdir) / "test.db"
        db.UPLOADS_PATH = Path(self._tmpdir) / "uploads"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_production_rejects_default_secret(self):
        with patch.dict(os.environ, {"ELIT21_ENV": "production", "ELIT21_SECRET": DEFAULT_SECRET}, clear=False):
            with self.assertRaises(RuntimeError):
                load_app_config()

    def test_init_db_adds_archival_payment_and_index_migrations(self):
        db.init_db()
        with db.get_connection() as conn:
            order_columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
            product_columns = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
            migrations = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations")
            }
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(orders)")
            }
        self.assertIn("paypal_order_id", order_columns)
        self.assertIn("capture_id", order_columns)
        self.assertIn("archived", product_columns)
        self.assertIn("deleted_at", product_columns)
        self.assertTrue({"0001", "0002", "0003", "0004"}.issubset(migrations))
        self.assertIn("idx_orders_paypal_order_id", indexes)
        self.assertIn("idx_orders_capture_id", indexes)


if __name__ == "__main__":
    unittest.main()
