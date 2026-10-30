"""Checking and cleaning uploaded images (Phase 9, task 9-02, PLAN Q-9-8; A27).

An upload is never trusted: not its name, not the type the browser says, not its bytes.

1. **Size** first (``ASSET_MAX_BYTES``), before decoding.
2. **Decoded** by Pillow from the bytes themselves: only JPEG, PNG and WebP are accepted, and
   the pixel count is checked from the header **before** the picture is decoded (a
   "decompression bomb" — a small file that expands to billions of pixels — is refused).
3. Fully decoded (a truncated or corrupt file is refused), turned the right way up, and
   **re-encoded** into a new file of the same format. Only the pixels are kept: EXIF (camera,
   GPS location), comments, text chunks and anything appended to the file are dropped.
4. Smallest side at least ``ASSET_MIN_SIDE`` pixels.

The result carries its real type, size and SHA-256.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
PNG_MODES = frozenset({"RGB", "RGBA", "L", "LA"})  # kept as they are; others become RGBA
WEBP_MODES = frozenset({"RGB", "RGBA"})


class ImageRejected(Exception):
    """Why an upload is not an acceptable image: a plain reason key."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CleanImage:
    content: bytes
    content_type: str
    width: int
    height: int
    sha256: str


def clean_image(data: bytes, *, max_bytes: int, min_side: int, max_pixels: int) -> CleanImage:
    if len(data) > max_bytes:
        raise ImageRejected("too_large")
    if not data:
        raise ImageRejected("empty")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            fmt = probe.format or ""
            if fmt not in FORMATS:
                raise ImageRejected("unsupported_type")
            width, height = probe.size
            if width * height > max_pixels:
                raise ImageRejected("too_many_pixels")
            probe.load()  # decode everything: a broken file fails here
            picture = ImageOps.exif_transpose(probe)
    except ImageRejected:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected("not_an_image") from None
    except (OSError, ValueError, SyntaxError):
        raise ImageRejected("not_an_image") from None
    if min(picture.size) < min_side:
        raise ImageRejected("too_small")
    out = io.BytesIO()
    if fmt == "JPEG":
        picture.convert("RGB").save(out, format="JPEG", quality=90, optimize=True)
    elif fmt == "PNG":
        keep = picture if picture.mode in PNG_MODES else picture.convert("RGBA")
        keep.save(out, format="PNG", optimize=True)
    else:
        keep = picture if picture.mode in WEBP_MODES else picture.convert("RGBA")
        keep.save(out, format="WEBP", quality=90)
    content = out.getvalue()
    return CleanImage(
        content=content,
        content_type=FORMATS[fmt],
        width=picture.size[0],
        height=picture.size[1],
        sha256=hashlib.sha256(content).hexdigest(),
    )
