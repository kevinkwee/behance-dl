"""Values that describe a gallery, its assets, and what a run has already saved."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .naming import safe_name


@dataclass(frozen=True)
class GalleryProject:
    """A Behance project reduced to what downloading it needs."""

    id: int
    name: str
    slug: str
    modules: tuple[dict[str, Any], ...]
    payload: dict[str, Any]

    @property
    def folder_name(self) -> str:
        slug = safe_name(self.slug, "")
        return f"{self.id}_{slug}" if slug else str(self.id)


@dataclass(frozen=True)
class ImageAsset:
    """One downloadable image and the CDN variant chosen for it."""

    file_prefix: str
    url: str
    width: int
    caption: str = ""

    @property
    def file_name(self) -> str:
        cdn_name = Path(urllib.parse.urlsplit(self.url).path).name
        return f"{self.file_prefix}_{safe_name(cdn_name, 'image')}"

    @property
    def position(self) -> int:
        """Return the module position the file prefix was built from."""
        return int(self.file_prefix.partition("_")[0])


@dataclass(frozen=True)
class TextBlock:
    """Author-written HTML that sits in page order among the page's assets."""

    position: int
    markup: str


@dataclass(frozen=True)
class EmbedAsset:
    """A module that is saved as a link instead of a file: an embed, a video, or a prototype."""

    position: int
    module_id: int
    caption: str
    source_url: str
    width: int
    height: int


@dataclass(frozen=True)
class GalleryPlan:
    """What one gallery will produce before anything is written."""

    project: GalleryProject
    images: tuple[ImageAsset, ...]
    embeds: tuple[EmbedAsset, ...]
    destination: Path
    expected_images: int
    texts: tuple[TextBlock, ...] = ()


@dataclass(frozen=True)
class SavedImage:
    """An image recorded in a gallery folder, and the CDN URL it came from."""

    url: str
    path: str


@dataclass(frozen=True)
class StoredImage:
    """Where an image ended up and whether this run wrote it."""

    path: Path
    written: bool
