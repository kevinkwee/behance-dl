"""Choosing which CDN variant of each image to download."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any

from .errors import GalleryError
from .gallery import (
    embed_assets,
    fetch_project,
    image_sources,
    is_behance_url,
    is_collection_module,
    module_image_sources,
    parse_gallery_id,
    text_blocks,
)
from .models import GalleryPlan, GalleryProject, ImageAsset, Slide

if TYPE_CHECKING:
    from pathlib import Path

    from .client import GalleryClient

_SOURCE_BUCKET = "source"
_STILL_BUCKET_SUFFIX = "_still"
_OPTIMISED_BUCKET = "_opt_"
_MAX_PIXEL_DIGITS = 6
_MAX_PIXELS = 100_000


def bucket(url: str) -> str:
    """Return the CDN bucket a project image URL was built from."""
    segments = urllib.parse.urlsplit(url).path.split("/")
    if "project_modules" in segments:
        index = segments.index("project_modules") + 1
        if index < len(segments):
            return segments[index]
    return ""


def bucket_rank(bucket_name: str) -> int:
    """Rank equally wide variants, preferring the least processed copy."""
    if bucket_name == _SOURCE_BUCKET:
        return 3
    if _OPTIMISED_BUCKET in bucket_name:
        return 1
    return 2


def candidate_sizes(image_source: dict[str, Any]) -> list[tuple[int, int, str]]:
    """Collect (width, bucket rank, URL) for the variants worth downloading.

    Stills are dropped when an animated variant exists, because a still bucket holds only
    the first frame of an animated image.
    """
    sizes = image_source.get("imageSizes") or {}
    variants: list[tuple[int, str, str]] = []
    for variant in sizes.get("allAvailable") or []:
        url = str(variant.get("url") or "")
        if not is_behance_url(url):
            continue
        if variant.get("type") == "WEBP" or "_webp" in url:
            continue
        variants.append((int(variant.get("width") or 0), bucket(url), url))
    animated = [entry for entry in variants if not entry[1].endswith(_STILL_BUCKET_SUFFIX)]
    chosen = animated or variants
    if chosen:
        return [(width, bucket_rank(name), url) for width, name, url in chosen]
    preview = str((sizes.get("size_disp") or {}).get("url") or image_source.get("src") or "")
    if not is_behance_url(preview):
        return []
    return [(int(image_source.get("width") or 0), 0, preview)]


def select_image_url(image_source: dict[str, Any], max_width: int | None) -> tuple[int, str] | None:
    """Pick the widest variant at or below max_width, else the smallest available.

    Without max_width the widest variant wins.
    """
    ordered = sorted(candidate_sizes(image_source), reverse=True)
    if not ordered:
        return None
    if max_width is None:
        width, _rank, url = ordered[0]
        return width, url
    within_limit = [entry for entry in ordered if entry[0] <= max_width]
    width, _rank, url = (
        within_limit[0] if within_limit else min(ordered, key=lambda entry: (entry[0], -entry[1]))
    )
    return width, url


def image_asset(
    image_source: dict[str, Any], file_prefix: str, max_width: int | None
) -> ImageAsset | None:
    """Build the asset for one image, or return None when it offers no usable variant."""
    selected = select_image_url(image_source, max_width)
    if selected is None:
        return None
    width, url = selected
    caption = image_source.get("caption")
    return ImageAsset(
        file_prefix=file_prefix,
        url=url,
        width=width,
        caption=caption if isinstance(caption, str) else "",
        display_width=_pixels(image_source.get("width")),
        display_height=_pixels(image_source.get("height")),
    )


def _pixels(value: object) -> int:
    """Read a payload pixel count, or return 0 when it is not a whole number in range."""
    number = 0
    if isinstance(value, str) and value.isdecimal() and len(value) <= _MAX_PIXEL_DIGITS:
        number = int(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        number = value
    return number if 0 < number <= _MAX_PIXELS else 0


def _text(value: object) -> str:
    """Read payload text, or return an empty string for any other shape."""
    return value if isinstance(value, str) else ""


def _flag(value: object) -> bool:
    """Read a payload flag, which the page data spells as either a boolean or 1."""
    return value is True or value == 1


def plan_slides(project: GalleryProject, max_width: int | None) -> list[Slide]:
    """Resolve each image-bearing module into the slide the page shows."""
    slides: list[Slide] = []
    for position, module in enumerate(project.modules, start=1):
        images: list[ImageAsset] = []
        for file_prefix, source in module_image_sources(module, position):
            asset = image_asset(source, file_prefix, max_width)
            if asset is not None:
                images.append(asset)
        if not images:
            continue
        collection = is_collection_module(module)
        slides.append(
            Slide(
                position=position,
                images=tuple(images),
                is_collection=collection,
                collection_caption=_text(module.get("caption")) if collection else "",
                is_full_bleed=_flag(module.get("fullBleed")),
            )
        )
    return slides


def plan_gallery(
    client: GalleryClient, gallery: str, max_width: int | None, output_root: Path
) -> GalleryPlan:
    """Fetch one gallery and resolve every asset it will produce."""
    gallery_id = parse_gallery_id(gallery)
    project = fetch_project(client, gallery_id)
    try:
        images_count = len(list(image_sources(project)))
        slides = plan_slides(project, max_width)
        embeds = embed_assets(project)
        texts = text_blocks(project)
    except (TypeError, ValueError, OverflowError, AttributeError) as error:
        raise GalleryError(f"gallery {gallery_id}: unexpected project data") from error
    return GalleryPlan(
        project=project,
        slides=tuple(slides),
        embeds=tuple(embeds),
        destination=output_root / project.folder_name,
        expected_images=images_count,
        texts=tuple(texts),
    )
