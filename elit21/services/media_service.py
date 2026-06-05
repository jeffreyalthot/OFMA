from __future__ import annotations

import mimetypes
import secrets
from io import BytesIO
from pathlib import Path

from elit21.db import UPLOADS_PATH

try:  # Pillow is optional in dev/test environments pinned to unreleased Python.
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:  # pragma: no cover - exercised when Pillow is unavailable
    Image = None
    ImageOps = None

    class UnidentifiedImageError(Exception):
        pass


PRODUCT_UPLOADS = UPLOADS_PATH / "products"
ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_DIMENSION = 4_000


class InvalidImageUpload(ValueError):
    """Raised when an uploaded product image fails security validation."""


def ensure_upload_dirs() -> None:
    PRODUCT_UPLOADS.mkdir(parents=True, exist_ok=True)


def guess_extension(mime_type: str | None, original_path: str | None = None) -> str:
    if original_path:
        ext = Path(original_path).suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp"}:
            return ".jpg" if ext == ".jpeg" else ext
    guessed = mimetypes.guess_extension((mime_type or "").strip().lower())
    if guessed in {".jpe", ".jpeg"}:
        return ".jpg"
    if guessed in {".jpg", ".png", ".webp"}:
        return guessed
    return ".jpg"


def _sanitize_with_pillow(content: bytes) -> tuple[bytes, str, str]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidImageUpload("Image trop lourde.")
    if Image is None or ImageOps is None:
        # Compatibility fallback for environments without Pillow. The admin UI
        # still restricts extensions, while production installs Pillow and uses
        # the strict branch above.
        return content, "image/jpeg", ".jpg"
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            original_format = image.format
            normalized = ImageOps.exif_transpose(image)
            if original_format == "SVG" or original_format not in ALLOWED_IMAGE_FORMATS:
                raise InvalidImageUpload("Format image refusé.")
            width, height = normalized.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise InvalidImageUpload("Dimensions image invalides.")
            if width > MAX_DIMENSION or height > MAX_DIMENSION:
                normalized.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            if normalized.mode not in {"RGB", "RGBA"}:
                normalized = normalized.convert("RGB")
            extension = ALLOWED_IMAGE_FORMATS[original_format]
            output = BytesIO()
            save_kwargs = {"optimize": True}
            mime_type = "image/jpeg"
            if extension == ".png":
                mime_type = "image/png"
                normalized.save(output, format="PNG", **save_kwargs)
            elif extension == ".webp":
                mime_type = "image/webp"
                normalized.save(output, format="WEBP", quality=85, **save_kwargs)
            else:
                if normalized.mode == "RGBA":
                    normalized = normalized.convert("RGB")
                normalized.save(output, format="JPEG", quality=88, **save_kwargs)
            return output.getvalue(), mime_type, extension
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageUpload("Contenu image invalide.") from exc


def save_product_image(
    *,
    product_id: int,
    index: int,
    content: bytes,
    mime_type: str,
    original_path: str | None = None,
) -> str:
    ensure_upload_dirs()
    if original_path and Path(original_path).suffix.lower() == ".svg":
        raise InvalidImageUpload("SVG refusé pour les uploads utilisateur.")
    sanitized_content, _sanitized_mime, sanitized_ext = _sanitize_with_pillow(content)
    extension = sanitized_ext if Image is not None else guess_extension(mime_type, original_path)
    file_name = f"product_{int(product_id)}_{index}_{secrets.token_urlsafe(16)}{extension}"
    image_path = (PRODUCT_UPLOADS / file_name).resolve()
    uploads_root = UPLOADS_PATH.parent.resolve()
    if uploads_root not in image_path.parents:
        raise InvalidImageUpload("Chemin image invalide.")
    image_path.write_bytes(sanitized_content)
    return str(image_path.relative_to(uploads_root))


def resolve_image_path(stored_path: str) -> Path:
    uploads_root = UPLOADS_PATH.parent.resolve()
    resolved = (uploads_root / stored_path).resolve()
    if uploads_root not in resolved.parents and resolved != uploads_root:
        raise InvalidImageUpload("Chemin image invalide.")
    return resolved
