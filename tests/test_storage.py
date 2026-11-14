"""Tests for saving images and the record of what was saved."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from behance_dl.models import GalleryPlan, GalleryProject, ImageAsset, SavedImage
from behance_dl.storage import (
    MANIFEST_NAME,
    download_images,
    is_recorded_name,
    load_saved,
    save_gallery,
    save_image,
    write_json,
)
from conftest import FakeClient

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPG = b"\xff\xd8\xff" + b"\x00" * 24


def make_plan(destination: Path, *urls: str) -> GalleryPlan:
    images = tuple(
        ImageAsset(file_prefix=f"{index:03d}", url=url, width=100)
        for index, url in enumerate(urls, start=1)
    )
    project = GalleryProject(id=1, name="P", slug="P", modules=(), payload={"id": 1})
    return GalleryPlan(
        project=project,
        images=images,
        embeds=(),
        destination=destination,
        expected_images=len(images),
    )


def test_write_json_replaces_atomically(tmp_path: Path) -> None:
    target = tmp_path / "data.json"

    write_json(target, {"a": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert list(tmp_path.glob("*.part")) == []


def test_write_json_escapes_a_lone_surrogate(tmp_path: Path) -> None:
    target = tmp_path / "data.json"

    write_json(target, {"name": "\ud800"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "\ud800"}


def test_load_saved_returns_an_empty_record_without_a_manifest(tmp_path: Path) -> None:
    assert load_saved(tmp_path) == {}


def test_load_saved_reads_valid_entries(tmp_path: Path) -> None:
    write_json(
        tmp_path / MANIFEST_NAME,
        {"001_a.png": {"url": "https://x/a.png", "path": "001_a.png"}},
    )

    assert load_saved(tmp_path) == {
        "001_a.png": SavedImage(url="https://x/a.png", path="001_a.png")
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"url": "https://x/a.png", "path": "project.json"},
        {"url": "https://x/a.png", "path": "../escape.png"},
        {"url": "https://x/a.png", "path": "002_other.png"},
        {"url": "https://x/a.png", "path": "001_a\u0000.png"},
        {"url": 5, "path": "001_a.png"},
        "not an object",
    ],
)
def test_load_saved_ignores_untrustworthy_entries(tmp_path: Path, entry: object) -> None:
    write_json(tmp_path / MANIFEST_NAME, {"001_a.png": entry})

    assert load_saved(tmp_path) == {}


def test_load_saved_ignores_an_unreadable_manifest(tmp_path: Path) -> None:
    (tmp_path / MANIFEST_NAME).write_bytes("{}".encode("utf-16"))

    assert load_saved(tmp_path) == {}


def test_load_saved_ignores_a_non_object_manifest(tmp_path: Path) -> None:
    write_json(tmp_path / MANIFEST_NAME, [1, 2])

    assert load_saved(tmp_path) == {}


def test_is_recorded_name_requires_a_plain_name_with_the_planned_stem() -> None:
    assert is_recorded_name("001_a.png", "001_a.jpg") is True
    assert is_recorded_name("001_a.png", "002_a.jpg") is False
    assert is_recorded_name("001_a.png", "sub/001_a.png") is False


def test_save_image_reuses_a_recorded_download(tmp_path: Path) -> None:
    existing = tmp_path / "001_a.png"
    existing.write_bytes(PNG)
    client = FakeClient()
    asset = ImageAsset(file_prefix="001", url="https://x/a.png", width=100)

    stored = save_image(client, asset, tmp_path, SavedImage(url=asset.url, path=existing.name))

    assert stored.written is False
    assert stored.path == existing
    assert client.requested == []


def test_save_image_refetches_when_the_recorded_url_differs(tmp_path: Path) -> None:
    client = FakeClient(images={"https://x/a.png": PNG})
    asset = ImageAsset(file_prefix="001", url="https://x/a.png", width=100)

    stored = save_image(
        client, asset, tmp_path, SavedImage(url="https://x/old.png", path="001_a.png")
    )

    assert stored.written is True
    assert stored.path.read_bytes() == PNG


def test_save_image_refetches_when_the_file_is_missing(tmp_path: Path) -> None:
    client = FakeClient(images={"https://x/a.png": PNG})
    asset = ImageAsset(file_prefix="001", url="https://x/a.png", width=100)

    stored = save_image(client, asset, tmp_path, SavedImage(url=asset.url, path="001_a.png"))

    assert stored.written is True


def test_download_images_records_success_and_counts_failures(tmp_path: Path) -> None:
    client = FakeClient(images={"https://x/a.png": PNG})
    plan = make_plan(tmp_path, "https://x/a.png", "https://x/b.png")
    recorded: dict[str, SavedImage] = {}

    failed = download_images(
        client,
        plan.images,
        tmp_path,
        {},
        workers=1,
        on_saved=lambda name, entry: recorded.__setitem__(name, entry),
    )

    assert failed == 1
    assert set(recorded) == {"001_a.png"}
    assert recorded["001_a.png"].url == "https://x/a.png"


def test_save_gallery_writes_metadata_and_the_manifest(tmp_path: Path) -> None:
    client = FakeClient(images={"https://x/a.png": PNG})
    plan = make_plan(tmp_path / "gallery", "https://x/a.png")

    failed = save_gallery(client, plan, {}, workers=1)

    assert failed == 0
    assert json.loads((plan.destination / "project.json").read_text(encoding="utf-8")) == {"id": 1}
    manifest = json.loads((plan.destination / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest == {"001_a.png": {"url": "https://x/a.png", "path": "001_a.png"}}


def test_save_gallery_removes_a_superseded_file(tmp_path: Path) -> None:
    destination = tmp_path / "gallery"
    destination.mkdir()
    stale = destination / "001_a.png"
    stale.write_bytes(b"old")
    client = FakeClient(images={"https://x/a.jpg": JPG})
    plan = make_plan(destination, "https://x/a.jpg")

    failed = save_gallery(
        client,
        plan,
        {"001_a.jpg": SavedImage(url="https://x/a.png", path="001_a.png")},
        workers=1,
    )

    assert failed == 0
    assert not stale.exists()


def test_save_gallery_keeps_a_locked_superseded_file(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "gallery"
    destination.mkdir()
    stale = destination / "001_a.png"
    stale.write_bytes(b"old")
    client = FakeClient(images={"https://x/a.jpg": JPG})
    plan = make_plan(destination, "https://x/a.jpg")

    def refuse(path: Path, missing_ok: bool = False) -> None:
        raise PermissionError(13, "in use")

    monkeypatch.setattr(Path, "unlink", refuse)

    failed = save_gallery(
        client,
        plan,
        {"001_a.jpg": SavedImage(url="https://x/a.png", path="001_a.png")},
        workers=1,
    )

    assert failed == 0


def test_save_gallery_reports_a_manifest_write_failure_without_failing(
    tmp_path: Path, monkeypatch
) -> None:
    client = FakeClient(images={"https://x/a.png": PNG})
    plan = make_plan(tmp_path / "gallery", "https://x/a.png")

    original = Path.write_text

    def refuse(self: Path, data: str, encoding: str | None = None, **kwargs: object) -> None:
        if self.name == MANIFEST_NAME + ".part":
            raise OSError(32, "in use")
        original(self, data, encoding=encoding or "utf-8", **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse)

    assert save_gallery(client, plan, {}, workers=1) == 0
