"""Errors the downloader raises on purpose."""

from __future__ import annotations


class BehanceError(RuntimeError):
    """Base class for every failure the downloader reports to the caller."""


class GalleryError(BehanceError):
    """Raised when a Behance page cannot be read or resolved into downloadable content."""


class DownloadError(BehanceError):
    """Raised when a remote image cannot be saved as a complete, genuine file."""
