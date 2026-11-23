"""Uploaded images are checked by decoding and re-saved clean; storage drivers (task 9-02)."""

from __future__ import annotations

import io
import uuid

import pytest
from app.core.storage import LocalStorage, S3Storage, StorageError, checked, new_key
from app.domains.creative.images import ImageRejected, clean_image
from PIL import Image

LIMITS = {"max_bytes": 2_000_000, "min_side": 600, "max_pixels": 20_000_000}


def picture(fmt="JPEG", size=(800, 600), mode="RGB", exif=None) -> bytes:
    out = io.BytesIO()
    image = Image.new(mode, size, (200, 30, 30) if mode == "RGB" else None)
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def gps_exif() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Camera Maker"  # Make
    exif[0x8825] = {1: "S", 2: (33.0, 52.0, 0.0)}  # GPSInfo
    return exif.tobytes()


@pytest.mark.parametrize(
    ("fmt", "kind"), [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")]
)
def test_accepted_formats_are_re_encoded(fmt, kind):
    clean = clean_image(picture(fmt), **LIMITS)
    assert (clean.content_type, clean.width, clean.height) == (kind, 800, 600)
    assert len(clean.sha256) == 64
    assert Image.open(io.BytesIO(clean.content)).format == fmt


def test_hidden_data_is_removed():
    original = picture(exif=gps_exif())
    assert b"Camera Maker" in original
    clean = clean_image(original + b"<?php system($_GET['x']); ?>", **LIMITS)
    assert b"Camera Maker" not in clean.content
    assert b"php" not in clean.content
    assert not Image.open(io.BytesIO(clean.content)).getexif()


def test_the_picture_is_turned_the_right_way_up():
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 degrees
    clean = clean_image(picture(size=(900, 700), exif=exif.tobytes()), **LIMITS)
    assert (clean.width, clean.height) == (700, 900)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "empty"),
        (b"#!/bin/sh\nrm -rf /\n", "not_an_image"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "not_an_image"),
        (picture("GIF", mode="P"), "unsupported_type"),
        (picture("BMP"), "unsupported_type"),
        (picture(size=(500, 900)), "too_small"),
    ],
)
def test_what_is_refused(data, reason):
    with pytest.raises(ImageRejected) as caught:
        clean_image(data, **LIMITS)
    assert caught.value.reason == reason


def test_size_and_pixel_limits_are_checked_before_decoding():
    big = picture(size=(1200, 1200))
    with pytest.raises(ImageRejected) as caught:
        clean_image(big, max_bytes=len(big) - 1, min_side=600, max_pixels=20_000_000)
    assert caught.value.reason == "too_large"
    with pytest.raises(ImageRejected) as caught:
        clean_image(big, max_bytes=2_000_000, min_side=600, max_pixels=1_000_000)
    assert caught.value.reason == "too_many_pixels"


def test_a_truncated_file_is_refused():
    data = picture(size=(1000, 1000))
    with pytest.raises(ImageRejected) as caught:
        clean_image(data[: len(data) // 2], **LIMITS)
    assert caught.value.reason == "not_an_image"


# ------------------------------------------------------------------ storage
def test_keys_are_random_and_under_the_organizations_prefix():
    org = uuid.uuid4()
    a, b = new_key(org, "image/png"), new_key(org, "image/png")
    assert a != b and a.startswith(f"org/{org}/assets/") and a.endswith(".png")
    for bad in ("../etc/passwd.png", "org//x.png", "Org/x.PNG", "x.exe", "/abs.jpg"):
        with pytest.raises(StorageError):
            checked(bad)


def test_local_storage(tmp_path):
    store = LocalStorage(tmp_path)
    key = new_key(uuid.uuid4(), "image/jpeg")
    store.put(key, b"pixels", "image/jpeg")
    assert store.get(key) == b"pixels"
    assert (tmp_path / key).stat().st_mode & 0o777 == 0o600
    assert not list((tmp_path / key).parent.glob(".upload-*"))
    with pytest.raises(StorageError):
        store.get(new_key(uuid.uuid4(), "image/jpeg"))


class FakeS3:
    """The two calls AdVegaX makes, as boto3's client answers them."""

    def __init__(self, fail: bool = False) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.fail = fail

    def put_object(self, *, Bucket, Key, Body, ContentType):  # noqa: N803
        if self.fail:
            raise RuntimeError("AccessDenied for bucket secret-bucket")
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, *, Bucket, Key):  # noqa: N803
        body, _ = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(body)}


def test_s3_storage_against_a_fake():
    fake = FakeS3()
    store = S3Storage(fake, "assets")
    key = new_key(uuid.uuid4(), "image/webp")
    store.put(key, b"pixels", "image/webp")
    assert fake.objects[("assets", key)] == (b"pixels", "image/webp")
    assert store.get(key) == b"pixels"
    with pytest.raises(StorageError) as caught:
        store.get(new_key(uuid.uuid4(), "image/webp"))
    assert str(caught.value) == "not_found"
    with pytest.raises(StorageError) as caught:
        S3Storage(FakeS3(fail=True), "assets").put(key, b"x", "image/webp")
    assert "secret-bucket" not in str(caught.value)
    with pytest.raises(StorageError):
        store.put("../x.png", b"x", "image/png")
