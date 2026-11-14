"""HTTP access to Behance, including its bot challenge and transient-failure retries."""

from __future__ import annotations

import http.client
import http.cookiejar
import re
import shutil
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from .errors import DownloadError, GalleryError

CHALLENGE_COOKIE = "js_challenge_value"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
TRANSFER_BLOCK_SIZE = 64 * 1024
MAX_BACKOFF_SECONDS = 30.0

_CHALLENGE_VALUE = re.compile(r"js_challenge_value=([0-9a-fA-F]{16,})")
_MAGIC_SUFFIXES = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)

T = TypeVar("T")


class BehanceClient:
    """HTTP session that satisfies Behance's cookie challenge and retries transient failures."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        attempts: int = 3,
        user_agent: str = USER_AGENT,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        self._timeout = timeout
        self._attempts = attempts
        self._user_agent = user_agent
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))

    def get_text(self, url: str) -> str:
        """Return the decoded body of a text resource."""
        return self._retry(lambda: self._read_text(url))

    def download(self, url: str, destination: Path) -> Path:
        """Save a remote image and return where it landed, named after its real format."""
        return self._retry(lambda: self._transfer(url, destination))

    def _read_text(self, url: str) -> str:
        with self._open(url) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, "replace")

    def _transfer(self, url: str, destination: Path) -> Path:
        partial = destination.with_name(destination.name + ".part")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._store_image(url, partial, destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

    def _store_image(self, url: str, partial: Path, destination: Path) -> Path:
        expected_size, content_type = self._copy_body(url, partial)
        if not content_type.startswith("image/"):
            raise DownloadError(f"{url} answered {content_type} instead of an image")
        suffix = detected_suffix(partial)
        if suffix is None:
            raise DownloadError(f"{url} did not return a recognised image format")
        received_size = partial.stat().st_size
        if expected_size and expected_size.isdecimal() and received_size != int(expected_size):
            raise DownloadError(f"{url} stopped after {received_size} of {expected_size} bytes")
        final_name = destination.with_suffix(suffix)
        partial.replace(final_name)
        return final_name

    def _copy_body(self, url: str, partial: Path) -> tuple[str | None, str]:
        """Stream a response body into the partial file and report its length and media type."""
        with self._open(url) as response:
            expected_size = response.headers.get("Content-Length")
            content_type = response.headers.get_content_type()
            with partial.open("wb") as handle:
                shutil.copyfileobj(response, handle, TRANSFER_BLOCK_SIZE)
            return expected_size, content_type

    def _open(self, url: str) -> http.client.HTTPResponse:
        host = urllib.parse.urlsplit(url).hostname or ""
        try:
            return self._opener.open(self._request(url), timeout=self._timeout)
        except urllib.error.HTTPError as error:
            if error.code != 403 or not self._solve_challenge(error, host):
                raise
        try:
            return self._opener.open(self._request(url), timeout=self._timeout)
        except urllib.error.HTTPError as error:
            if error.code == 403 and self._solve_challenge(error, host):
                raise GalleryError(f"{url} keeps answering Behance's bot challenge") from error
            raise

    def _request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers=self._headers())

    def _retry(self, action: Callable[[], T]) -> T:
        for attempt in range(1, self._attempts):
            try:
                return action()
            except urllib.error.HTTPError as error:
                if error.code not in RETRYABLE_STATUS:
                    raise
                retry_after = error.headers.get("Retry-After")
                error.close()
                self._pause(attempt, retry_after)
            except (
                urllib.error.URLError,
                http.client.HTTPException,
                TimeoutError,
                ConnectionError,
                ssl.SSLError,
                DownloadError,
            ):
                self._pause(attempt, None)
        return action()

    def _pause(self, attempt: int, retry_after: str | None) -> None:
        requested = parse_retry_after(retry_after)
        if requested is not None:
            time.sleep(min(requested, MAX_BACKOFF_SECONDS))
        else:
            time.sleep(min(2**attempt, MAX_BACKOFF_SECONDS))

    def _solve_challenge(self, error: urllib.error.HTTPError, host: str) -> bool:
        with error:
            body = error.read().decode("utf-8", "replace")
        match = _CHALLENGE_VALUE.search(body)
        if match is None:
            return False
        self._jar.set_cookie(challenge_cookie(match.group(1), host))
        return True

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent, "Accept-Language": "en-US,en;q=0.9"}


def challenge_cookie(value: str, host: str) -> http.cookiejar.Cookie:
    """Build the cookie Behance's challenge page asks the browser to set."""
    return http.cookiejar.Cookie(
        version=0,
        name=CHALLENGE_COOKIE,
        value=value,
        port=None,
        port_specified=False,
        domain=host,
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


def parse_retry_after(value: str | None) -> float | None:
    """Read a Retry-After delay in seconds, ignoring dates and negative values."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def detected_suffix(path: Path) -> str | None:
    """Return the extension matching the file's magic bytes, if it is an image we know."""
    with path.open("rb") as handle:
        head = handle.read(16)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    for magic, suffix in _MAGIC_SUFFIXES:
        if head.startswith(magic):
            return suffix
    return None
