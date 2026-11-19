"""Reading a gallery page and the project data Behance inlines in it."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from .errors import GalleryError
from .models import EmbedAsset, GalleryProject, TextBlock

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .client import GalleryClient

BEHANCE_ORIGIN = "https://www.behance.net"

_STORE_STATE = re.compile(
    r'<script type="application/json" id="beconfig-store_state">(.*?)</script>',
    re.DOTALL,
)
_GALLERY_PATH = re.compile(r"/gallery/(\d+)")
_IFRAME_SOURCE = re.compile(r'<iframe[^>]+src="([^"]+)"', re.IGNORECASE)
_EMBED_MODULE_TYPES = frozenset({"EmbedModule", "VideoModule"})


def is_behance_host(host: str) -> bool:
    """Report whether a host belongs to Behance or one of its subdomains."""
    return host == "behance.net" or host.endswith(".behance.net")


def is_behance_url(url: str) -> bool:
    """Report whether a payload URL points at Behance over https."""
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and is_behance_host(parts.hostname or "")


def parse_gallery_id(gallery: str) -> int:
    """Return the numeric project id of a Behance gallery URL or bare id."""
    candidate = gallery.strip()
    if candidate.isdecimal():
        return int(candidate)
    parts = urllib.parse.urlsplit(candidate)
    host = parts.hostname or ""
    if host and not is_behance_host(host):
        raise GalleryError(f"{gallery!r} is not a Behance gallery URL")
    match = _GALLERY_PATH.search(parts.path)
    if match is None:
        raise GalleryError(f"{gallery!r} is not a Behance gallery URL")
    return int(match.group(1))


def fetch_project(client: GalleryClient, gallery_id: int) -> GalleryProject:
    """Load the project payload embedded in a gallery page."""
    # Behance answers 404 for /gallery/{id} alone and ignores whatever slug follows it.
    page = client.get_text(f"{BEHANCE_ORIGIN}/gallery/{gallery_id}/gallery")
    match = _STORE_STATE.search(page)
    project_state: Any = None
    if match is not None:
        try:
            state = json.loads(match.group(1))
        except (ValueError, RecursionError) as error:
            raise GalleryError(f"gallery {gallery_id}: unreadable project data") from error
        project_state = state.get("project") if isinstance(state, dict) else None
    payload = project_state.get("project") if isinstance(project_state, dict) else None
    if not isinstance(payload, dict) or not payload:
        raise GalleryError(
            f"gallery {gallery_id}: the page carries no public project data "
            "(removed, private, or behind a login)"
        )
    modules = payload.get("modules") or payload.get("allModules") or []
    if not isinstance(modules, list) or not all(isinstance(module, dict) for module in modules):
        raise GalleryError(f"gallery {gallery_id}: unexpected project data")
    return GalleryProject(
        id=gallery_id,
        name=str(payload.get("name") or ""),
        slug=str(payload.get("slug") or ""),
        modules=tuple(modules),
        payload=payload,
    )


def image_sources(project: GalleryProject) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield the file prefix and image payload of every image in the project."""
    for position, module in enumerate(project.modules, start=1):
        yield from module_image_sources(module, position)


def is_collection_module(module: dict[str, Any]) -> bool:
    """Report whether a module lays several images out as one row."""
    return module.get("__typename") == "MediaCollectionModule"


def module_image_sources(
    module: dict[str, Any], position: int
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield the file prefix and image payload of every image one module shows."""
    if module.get("__typename") == "ImageModule":
        yield f"{position:03d}", module
    elif is_collection_module(module):
        components = module.get("components") or []
        for index, component in enumerate(components, start=1):
            yield f"{position:03d}_{index:02d}", component


def text_blocks(project: GalleryProject) -> list[TextBlock]:
    """Collect the page's text modules in page order."""
    blocks: list[TextBlock] = []
    for position, module in enumerate(project.modules, start=1):
        if module.get("__typename") != "TextModule":
            continue
        markup = module.get("text")
        blocks.append(
            TextBlock(position=position, markup=markup if isinstance(markup, str) else "")
        )
    return blocks


def embed_assets(project: GalleryProject) -> list[EmbedAsset]:
    """Collect the modules that point at external media instead of hosting an image."""
    assets: list[EmbedAsset] = []
    for position, module in enumerate(project.modules, start=1):
        if module.get("__typename") not in _EMBED_MODULE_TYPES:
            continue
        markup = str(
            module.get("fluidEmbed") or module.get("originalEmbed") or module.get("embed") or ""
        )
        match = _IFRAME_SOURCE.search(markup)
        assets.append(
            EmbedAsset(
                position=position,
                module_id=int(module.get("id") or 0),
                caption=str(module.get("caption") or ""),
                source_url=html.unescape(match.group(1)) if match else "",
                width=int(module.get("originalWidth") or module.get("width") or 0),
                height=int(module.get("originalHeight") or module.get("height") or 0),
            )
        )
    return assets
