"""Shared doubles for tests that must not touch the network."""

from __future__ import annotations

import email.message
import io
import json
from pathlib import Path

import pytest

from behance_dl.models import GalleryProject

CDN = "https://mir-s3-cdn-cf.behance.net/project_modules"


class FakeHeaders(email.message.Message):
    """Headers with the accessors the downloader uses."""

    def __init__(self, content_type: str = "image/png", length: int | None = None) -> None:
        super().__init__()
        self["Content-Type"] = content_type
        if length is not None:
            self["Content-Length"] = str(length)

    def get_content_type(self) -> str:
        return self["Content-Type"].split(";")[0].strip()

    def get_content_charset(self) -> str | None:
        return "utf-8"


class FakeResponse:
    """A response body usable as a context manager."""

    def __init__(self, body: bytes, content_type: str = "image/png", length: int | None = None):
        self._body = body
        self._stream = io.BytesIO(body)
        self.headers = FakeHeaders(content_type, len(body) if length is None else length)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeOpener:
    """Opener that replays a scripted sequence of responses and errors."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls: list[str] = []

    def open(self, request: object, timeout: float | None = None) -> object:
        self.calls.append(getattr(request, "full_url", str(request)))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    """Stand-in for BehanceClient that serves prepared bodies instead of HTTP."""

    def __init__(self, pages: dict[int, str] | None = None, images: dict[str, bytes] | None = None):
        self._pages = pages or {}
        self._images = images or {}
        self.requested: list[str] = []

    def get_text(self, url: str) -> str:
        self.requested.append(url)
        for gallery_id, page in self._pages.items():
            if f"/gallery/{gallery_id}/" in url:
                return page
        raise AssertionError(f"unexpected page request: {url}")

    def download(self, url: str, destination: Path) -> Path:
        self.requested.append(url)
        from behance_dl.errors import DownloadError

        if url not in self._images:
            raise DownloadError(f"{url} unavailable")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self._images[url])
        return destination


def store_state_page(payload: object) -> str:
    """Render a gallery page that carries the given project payload."""
    state = json.dumps({"project": {"project": payload}})
    return (
        "<html><head></head><body>"
        f'<script type="application/json" id="beconfig-store_state">{state}</script>'
        "</body></html>"
    )


def image_module(module_id: int, variants: list[dict[str, object]], **extra: object) -> dict:
    """Build an ImageModule payload."""
    module = {
        "__typename": "ImageModule",
        "id": module_id,
        "width": extra.pop("width", 100),
        "caption": extra.pop("caption", ""),
        "imageSizes": {"allAvailable": variants},
    }
    module.update(extra)
    return module


def variant(
    bucket_name: str, width: int, name: str = "abc", kind: str = "JPG"
) -> dict[str, object]:
    """Build one allAvailable entry."""
    return {"url": f"{CDN}/{bucket_name}/{name}.png", "width": width, "type": kind}


@pytest.fixture
def project() -> GalleryProject:
    """A minimal project wrapping one image module."""
    return GalleryProject(
        id=123,
        name="Example",
        slug="Example-Slug",
        modules=(image_module(1, [variant("source", 2000)]),),
        payload={"id": 123, "name": "Example"},
    )
