from __future__ import annotations

import mimetypes
from pathlib import Path

from elit21.db import UPLOADS_PATH

PRODUCT_UPLOADS = UPLOADS_PATH / "products"


def ensure_upload_dirs() -> None:
    PRODUCT_UPLOADS.mkdir(parents=True, exist_ok=True)


def guess_extension(mime_type: str | None, original_path: str | None = None) -> str:
    if original_path:
        ext = Path(original_path).suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp"}:
            return ext
    guessed = mimetypes.guess_extension((mime_type or "").strip().lower())
    if guessed in {".jpe", ".jpeg"}:
        return ".jpg"
    if guessed in {".jpg", ".png", ".webp"}:
        return guessed
    return ".jpg"


def save_product_image(*, product_id: int, index: int, content: bytes, mime_type: str, original_path: str | None = None) -> str:
    ensure_upload_dirs()
    extension = guess_extension(mime_type, original_path)
    file_name = f"product_{product_id}_{index}{extension}"
    image_path = PRODUCT_UPLOADS / file_name
    image_path.write_bytes(content)
    return str(image_path.relative_to(UPLOADS_PATH.parent))


def resolve_image_path(stored_path: str) -> Path:
    return (UPLOADS_PATH.parent / stored_path).resolve()
