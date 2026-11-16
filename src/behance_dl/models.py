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
    """One downloadable image, the CDN variant chosen for it, and the size the page shows it at."""

    file_prefix: str
    url: str
    width: int
    caption: str = ""
    display_width: int = 0
    display_height: int = 0

    @property
    def file_name(self) -> str:
        cdn_name = Path(urllib.parse.urlsplit(self.url).path).name
        return f"{self.file_prefix}_{safe_name(cdn_name, 'image')}"


@dataclass(frozen=True)
class Slide:
    """One page module and the images it shows, in page order."""

    position: int
    images: tuple[ImageAsset, ...]
    is_collection: bool = False
    collection_caption: str = ""
    is_full_bleed: bool = False


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
    slides: tuple[Slide, ...]
    embeds: tuple[EmbedAsset, ...]
    destination: Path
    expected_images: int
    texts: tuple[TextBlock, ...] = ()

    @property
    def images(self) -> tuple[ImageAsset, ...]:
        """Return every planned image in the order it is downloaded."""
        return tuple(asset for slide in self.slides for asset in slide.images)

    @property
    def entries(self) -> tuple[Slide | EmbedAsset | TextBlock, ...]:
        """Return the page's modules in page order, slides first where positions tie."""
        return tuple(
            sorted((*self.slides, *self.embeds, *self.texts), key=lambda entry: entry.position)
        )


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
