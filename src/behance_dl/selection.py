"""Choosing which CDN variant of each image to download."""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from .client import BehanceClient
from .errors import GalleryError
from .gallery import (
    embed_assets,
    fetch_project,
    image_sources,
    is_behance_url,
    parse_gallery_id,
    text_blocks,
)
from .models import GalleryPlan, ImageAsset

_SOURCE_BUCKET = "source"
_STILL_BUCKET_SUFFIX = "_still"
_OPTIMISED_BUCKET = "_opt_"


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
    )


def plan_gallery(
    client: BehanceClient, gallery: str, max_width: int | None, output_root: Path
) -> GalleryPlan:
    """Fetch one gallery and resolve every asset it will produce."""
    gallery_id = parse_gallery_id(gallery)
    project = fetch_project(client, gallery_id)
    try:
        sources = list(image_sources(project))
        images: list[ImageAsset] = []
        for file_prefix, image_source in sources:
            asset = image_asset(image_source, file_prefix, max_width)
            if asset is not None:
                images.append(asset)
        embeds = embed_assets(project)
        texts = text_blocks(project)
    except (TypeError, ValueError, OverflowError, AttributeError) as error:
        raise GalleryError(f"gallery {gallery_id}: unexpected project data") from error
    return GalleryPlan(
        project=project,
        images=tuple(images),
        embeds=tuple(embeds),
        destination=output_root / project.folder_name,
        expected_images=len(sources),
        texts=tuple(texts),
    )
