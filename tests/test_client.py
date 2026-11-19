"""Tests for the HTTP client, its challenge handling and its retries."""

from __future__ import annotations

import email.message
import io
import urllib.error
from typing import TYPE_CHECKING

import pytest

from behance_dl.client import (
    CHALLENGE_COOKIE,
    IMAGE,
    VIDEO,
    BehanceClient,
    SameHostRedirects,
    detected_suffix,
    parse_retry_after,
    suffix_from_head,
)
from behance_dl.errors import DownloadError, GalleryError
from conftest import FakeOpener, FakeResponse

if TYPE_CHECKING:
    from pathlib import Path

URL = "https://www.behance.net/gallery/1/gallery"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
CHALLENGE_BODY = (
    b'<script>document.cookie = "js_challenge_value=' + b"a" * 64 + b'; Path=/";</script>'
)


def http_error(code: int, body: bytes = b"", **headers: str) -> urllib.error.HTTPError:
    """Build an HTTPError that carries a readable body."""
    message = email.message.Message()
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    return urllib.error.HTTPError(URL, code, "error", message, io.BytesIO(body))


def make_client(outcomes: list[object], attempts: int = 3) -> tuple[BehanceClient, FakeOpener]:
    """Return a client wired to a scripted opener."""
    client = BehanceClient(timeout=1.0, attempts=attempts)
    opener = FakeOpener(outcomes)
    client._opener = opener  # noqa: SLF001  # the client builds its own opener
    return client, opener


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"\x89PNG\r\n\x1a\nrest", ".png"),
        (b"\xff\xd8\xffrest", ".jpg"),
        (b"GIF89arest", ".gif"),
        (b"GIF87arest", ".gif"),
        (b"RIFF\x00\x00\x00\x00WEBPrest", ".webp"),
        (b"<html>not an image</html>", None),
    ],
)
def test_detected_suffix_uses_magic_bytes(
    tmp_path: Path, body: bytes, expected: str | None
) -> None:
    sample = tmp_path / "sample"
    sample.write_bytes(body)

    assert detected_suffix(sample) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("5", 5.0), ("0", 0.0), ("-1", None), ("soon", None), (None, None)],
)
def test_parse_retry_after_reads_seconds(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value) == expected


def test_get_text_solves_the_challenge_and_retries() -> None:
    client, opener = make_client([http_error(403, CHALLENGE_BODY), FakeResponse(b"page")])

    assert client.get_text(URL) == "page"
    assert len(opener.calls) == 2
    cookie = next(iter(client._jar))  # noqa: SLF001  # the client exposes no jar
    assert cookie.name == CHALLENGE_COOKIE
    assert cookie.value == "a" * 64


def test_get_text_reraises_a_403_without_a_challenge() -> None:
    client, _opener = make_client([http_error(403, b"forbidden")])

    with pytest.raises(urllib.error.HTTPError):
        client.get_text(URL)


def test_get_text_gives_up_when_the_challenge_repeats() -> None:
    client, _opener = make_client(
        [http_error(403, CHALLENGE_BODY), http_error(403, CHALLENGE_BODY)]
    )

    with pytest.raises(GalleryError):
        client.get_text(URL)


def test_retryable_statuses_are_retried() -> None:
    client, opener = make_client(
        [http_error(503, Retry_After="0"), FakeResponse(b"page")], attempts=2
    )

    assert client.get_text(URL) == "page"
    assert len(opener.calls) == 2


def test_non_retryable_statuses_fail_immediately() -> None:
    client, opener = make_client([http_error(404)], attempts=3)

    with pytest.raises(urllib.error.HTTPError):
        client.get_text(URL)
    assert len(opener.calls) == 1


def test_attempts_are_exhausted_before_giving_up() -> None:
    client, opener = make_client(
        [http_error(503, Retry_After="0"), http_error(503, Retry_After="0")], attempts=2
    )

    with pytest.raises(urllib.error.HTTPError):
        client.get_text(URL)
    assert len(opener.calls) == 2


def test_download_returns_the_path_matching_the_real_format(tmp_path: Path) -> None:
    client, _opener = make_client([FakeResponse(PNG, "image/png")])

    stored = client.download(URL, tmp_path / "001_abc.png")

    assert stored.name == "001_abc.png"
    assert stored.read_bytes() == PNG


def test_download_corrects_a_mislabelled_extension(tmp_path: Path) -> None:
    client, _opener = make_client([FakeResponse(b"\xff\xd8\xff" + b"\x00" * 8, "image/png")])

    stored = client.download(URL, tmp_path / "001_abc.png")

    assert stored.name == "001_abc.jpg"


def test_download_rejects_a_non_image_body(tmp_path: Path) -> None:
    client, _opener = make_client([FakeResponse(b"<html></html>", "text/html")], attempts=1)

    with pytest.raises(DownloadError):
        client.download(URL, tmp_path / "001_abc.png")

    assert list(tmp_path.iterdir()) == []


def test_download_rejects_an_unknown_format(tmp_path: Path) -> None:
    client, _opener = make_client([FakeResponse(b"plain bytes", "image/png")], attempts=1)

    with pytest.raises(DownloadError):
        client.download(URL, tmp_path / "001_abc.png")

    assert list(tmp_path.iterdir()) == []


def test_download_rejects_a_truncated_body(tmp_path: Path) -> None:
    client, _opener = make_client(
        [FakeResponse(PNG, "image/png", length=len(PNG) + 10)], attempts=1
    )

    with pytest.raises(DownloadError):
        client.download(URL, tmp_path / "001_abc.png")

    assert list(tmp_path.iterdir()) == []


def test_download_retries_a_dropped_connection(tmp_path: Path) -> None:
    client, opener = make_client([ConnectionResetError("reset"), FakeResponse(PNG)], attempts=2)

    assert client.download(URL, tmp_path / "001.png").exists()
    assert len(opener.calls) == 2


@pytest.mark.parametrize(("attempts", "timeout"), [(0, 30.0), (3, 0.0), (3, -1.0)])
def test_client_rejects_invalid_settings(attempts: int, timeout: float) -> None:
    with pytest.raises(ValueError, match="must be"):
        BehanceClient(attempts=attempts, timeout=timeout)


def _response(body: bytes, content_type: str) -> FakeResponse:
    return FakeResponse(body, content_type)


MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 24


def test_image_download_rejects_video_bytes(tmp_path: Path) -> None:
    client, _opener = make_client([_response(MP4_BYTES, "image/png")], attempts=1)

    with pytest.raises(DownloadError, match="where image/ was expected"):
        client.download(URL, tmp_path / "001_a.png", kind=IMAGE)

    assert list(tmp_path.iterdir()) == []


def test_video_download_accepts_a_media_body(tmp_path: Path) -> None:
    client, _opener = make_client([_response(MP4_BYTES, "video/mp4")])

    stored = client.download(URL, tmp_path / "001_a.mp4", kind=VIDEO)

    assert stored.suffix == ".mp4"
    assert stored.read_bytes() == MP4_BYTES


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"<html></html>", "text/html"),
        (PNG, "image/png"),
        (PNG, "video/mp4"),
    ],
)
def test_video_download_rejects_non_video_payloads(
    tmp_path: Path, body: bytes, content_type: str
) -> None:
    client, _opener = make_client([_response(body, content_type)], attempts=1)

    with pytest.raises(DownloadError):
        client.download(URL, tmp_path / "001_a.mp4", kind=VIDEO)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (MP4_BYTES, ".mp4"),
        (b"\x00\x00\x00\x1cftypavif" + b"\x00" * 12, ".avif"),
        (b"\x00\x00\x00\x1cftypheic" + b"\x00" * 12, ".heic"),
        (b"\x1aE\xdf\xa3" + b"\x00" * 12, ".webm"),
        (b"plain", None),
    ],
)
def test_suffix_from_head_identifies_containers(head: bytes, expected: str | None) -> None:
    assert suffix_from_head(head) == expected


def _redirect(newurl: str) -> urllib.request.Request:
    return urllib.request.Request(URL)


@pytest.mark.parametrize(
    "newurl",
    ["http://www.behance.net/other", "https://evil.example.com/x", "ftp://www.behance.net/x"],
)
def test_redirects_off_host_or_off_https_are_refused(newurl: str) -> None:
    handler = SameHostRedirects()

    with pytest.raises(urllib.error.HTTPError, match="refused redirect"):
        handler.redirect_request(
            _redirect(URL), io.BytesIO(b""), 302, "Found", email.message.Message(), newurl
        )


def test_same_host_https_redirects_are_followed() -> None:
    handler = SameHostRedirects()

    request = handler.redirect_request(
        _redirect(URL),
        io.BytesIO(b""),
        302,
        "Found",
        email.message.Message(),
        "https://www.behance.net/elsewhere",
    )

    assert request is not None
    assert request.full_url == "https://www.behance.net/elsewhere"
