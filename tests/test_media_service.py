import shutil
import unittest
from pathlib import Path

from elit21.db import UPLOADS_PATH
from elit21.services import media_service


class MediaServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        product_dir = UPLOADS_PATH / "products"
        if product_dir.exists():
            shutil.rmtree(product_dir)

    def test_guess_extension_prefers_original_path(self):
        ext = media_service.guess_extension("image/jpeg", "demo.webp")
        self.assertEqual(ext, ".webp")

    def test_save_product_image_creates_file_and_relative_path(self):
        relative = media_service.save_product_image(
            product_id=99,
            index=1,
            content=b"fake-image",
            mime_type="image/png",
        )
        self.assertTrue(relative.startswith("uploads/products/"))
        resolved = media_service.resolve_image_path(relative)
        self.assertTrue(Path(resolved).exists())


if __name__ == "__main__":
    unittest.main()
