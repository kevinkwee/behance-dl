"""Downloading video modules from Behance's player or a supported external host.

Behance hosts video through Adobe's Creative Cloud player. The iframe itself carries no
media, but the player page it loads lists the stream sources, and the CDN serves direct
MP4 renditions that the signed token in those sources unlocks. External hosts such as
YouTube are handled through the optional yt-dlp extra.

Interactive embeds such as Figma prototypes are not video and stay links in embeds.json.
"""

from __future__ import annotations

import html
import re
import sys
import tempfile
import urllib.error
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .client import VIDEO, BehanceClient
from .errors import DownloadError
from .models import EmbedAsset
from .naming import safe_name
from .storage import remove_superseded

CCV_PLAYER_HOST = "www-ccv.adobe.io"
CCV_MEDIA_HOST = "cdn-prod-ccv.adobe.com"
EXTERNAL_VIDEO_HOSTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "dailymotion.com",
    "dai.ly",
)
EXTERNAL_VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov")

_SOURCE = re.compile(r'<source[^>]+src="([^"]+)"', re.IGNORECASE)
_ASSET_ID = re.compile(r"/player/ccv/([A-Za-z0-9_-]+)/")
_RESOLUTION = re.compile(r"RESOLUTION=\d+x(\d+)")
_RENDITION_HEIGHT = re.compile(r"_(\d+)\.mp4$")


@dataclass(frozen=True)
class ResolvedVideo:
    """A reachable video file, with the height that was chosen and a fallback."""

    url: str
    height: int
    fallback_url: str = ""


def is_ccv_player_url(url: str) -> bool:
    """Report whether a URL is a Behance video player page."""
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname == CCV_PLAYER_HOST


def is_ccv_media_url(url: str) -> bool:
    """Report whether a URL points at Adobe's video CDN over https."""
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname == CCV_MEDIA_HOST


def is_external_video_url(url: str) -> bool:
    """Report whether a URL belongs to a host the optional yt-dlp extra can handle."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https":
        return False
    return any(host == known or host.endswith("." + known) for known in EXTERNAL_VIDEO_HOSTS)


def video_assets(embeds: Sequence[EmbedAsset]) -> list[EmbedAsset]:
    """Return the embeds that name a downloadable video rather than an interactive app."""
    return [
        embed
        for embed in embeds
        if is_ccv_player_url(embed.source_url) or is_external_video_url(embed.source_url)
    ]


def parse_sources(page: str) -> list[str]:
    """Return the media URLs a player page offers, unescaped and allowlisted."""
    sources = [html.unescape(match.group(1)) for match in _SOURCE.finditer(page)]
    return [source for source in sources if is_ccv_media_url(source)]


def playlist_heights(playlist: str) -> list[int]:
    """Return the rendition heights a master playlist advertises, tallest first."""
    return sorted({int(match.group(1)) for match in _RESOLUTION.finditer(playlist)}, reverse=True)


def choose_height(heights: Sequence[int], max_height: int | None) -> int | None:
    """Pick the tallest rendition at or below max_height, else the shortest available."""
    ordered = sorted(heights, reverse=True)
    if not ordered:
        return None
    if max_height is None:
        return ordered[0]
    within_limit = [height for height in ordered if height <= max_height]
    return within_limit[0] if within_limit else ordered[-1]


def build_rendition_url(playlist_url: str, asset_id: str, height: int) -> str:
    """Build the direct MP4 URL for a rendition, keeping the playlist's signed token."""
    parts = urllib.parse.urlsplit(playlist_url)
    path = f"/{asset_id}/rend/{asset_id}_{height}.mp4"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def ccv_asset_id(url: str) -> str:
    """Return the Adobe asset id encoded in a player URL, or an empty string."""
    match = _ASSET_ID.search(url)
    return match.group(1) if match else ""


def resolve_behance_video(
    client: BehanceClient, embed: EmbedAsset, max_height: int | None
) -> ResolvedVideo:
    """Turn a Behance player embed into a direct MP4 URL, preferring the best rendition."""
    if not is_ccv_player_url(embed.source_url):
        raise DownloadError(f"{embed.source_url} is not a Behance video player")
    sources = parse_sources(client.get_text(embed.source_url))
    playlist = next((source for source in sources if ".m3u8" in source), "")
    listed_mp4 = next((source for source in sources if ".mp4" in source), "")
    asset_id = ccv_asset_id(embed.source_url)
    height = (
        choose_height(playlist_heights(client.get_text(playlist)), max_height) if playlist else None
    )
    if asset_id and playlist and height is not None:
        return ResolvedVideo(
            url=build_rendition_url(playlist, asset_id, height),
            height=height,
            fallback_url=listed_mp4,
        )
    if listed_mp4:
        return ResolvedVideo(url=listed_mp4, height=rendition_height(listed_mp4))
    raise DownloadError(f"{embed.source_url} exposes no downloadable video")


def rendition_height(url: str) -> int:
    """Read the height encoded in a rendition file name, or zero when absent."""
    match = _RENDITION_HEIGHT.search(urllib.parse.urlsplit(url).path)
    return int(match.group(1)) if match else 0


def download_videos(
    client: BehanceClient,
    embeds: Sequence[EmbedAsset],
    destination: Path,
    *,
    max_height: int | None,
    reuse: ReuseLookup,
) -> int:
    """Download every video module, returning how many failed.

    ``reuse`` decides whether a module already has a usable file on disk, so the caller
    owns the policy and this function has no flag that changes its behaviour.
    """
    assets = video_assets(embeds)
    skipped = [
        embed
        for embed in embeds
        if embed.source_url
        and not is_ccv_player_url(embed.source_url)
        and not is_external_video_url(embed.source_url)
    ]
    for embed in skipped:
        print(
            f"note: module {embed.position} is not a video, keeping its link in embeds.json",
            file=sys.stderr,
        )
    if not assets:
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    failed = 0
    for embed in assets:
        try:
            stored = _save_video(client, embed, destination, max_height, reuse)
        except Exception as error:  # noqa: BLE001  # one failed video must not stop the rest
            failed += 1
            print(f"video failed {embed.position:03d}: {error}", file=sys.stderr)
            continue
        status = "saved " if stored.written else "exists"
        print(f"{status} {stored.path.name}")
    if failed:
        print(f"{failed} of {len(assets)} videos failed", file=sys.stderr)
    return failed


def reuse_downloaded(max_height: int | None) -> ReuseLookup:
    """Build the lookup that reuses a file already on disk at a usable height."""

    def lookup(destination: Path, embed: EmbedAsset) -> StoredVideo | None:
        if is_ccv_player_url(embed.source_url):
            return _existing_video(
                destination, embed.position, ccv_asset_id(embed.source_url), max_height
            )
        return _existing_external(destination, embed.position)

    return lookup


def no_reuse(_destination: Path, _embed: EmbedAsset) -> StoredVideo | None:
    """Skip the on-disk check, so every video is fetched again."""
    return None


ReuseLookup = Callable[[Path, EmbedAsset], "StoredVideo | None"]


@dataclass(frozen=True)
class StoredVideo:
    """Where a video ended up and whether this run wrote it."""

    path: Path
    written: bool


def video_file_name(position: int, asset_id: str, height: int, url: str) -> str:
    """Name a video from validated parts, never from raw remote text."""
    if asset_id and height:
        return f"{position:03d}_{asset_id}_{height}.mp4"
    stem = safe_name(Path(urllib.parse.urlsplit(url).path).stem, "video")
    return f"{position:03d}_{stem}.mp4"


def _save_video(
    client: BehanceClient,
    embed: EmbedAsset,
    destination: Path,
    max_height: int | None,
    reuse: ReuseLookup,
) -> StoredVideo:
    existing = reuse(destination, embed)
    if existing is not None:
        return existing
    if is_ccv_player_url(embed.source_url):
        return _download_ccv(client, embed, destination, max_height)
    return _save_external(embed, destination)


def _existing_video(
    destination: Path, position: int, asset_id: str, max_height: int | None
) -> StoredVideo | None:
    """Find a usable download, so a re-run needs no network."""
    pattern = f"{position:03d}_{asset_id}_*.mp4" if asset_id else f"{position:03d}_*.mp4"
    for path in sorted(destination.glob(pattern)):
        if path.stat().st_size <= 0:
            continue
        height = rendition_height(path.name)
        if max_height is not None and height > max_height:
            continue
        return StoredVideo(path=path, written=False)
    return None


def _download_ccv(
    client: BehanceClient,
    embed: EmbedAsset,
    destination: Path,
    max_height: int | None,
) -> StoredVideo:
    """Fetch the best rendition, naming the file after the URL that actually answered."""
    asset_id = ccv_asset_id(embed.source_url)
    resolved = resolve_behance_video(client, embed, max_height)
    candidates = [(resolved.url, resolved.height)]
    if resolved.fallback_url:
        candidates.append((resolved.fallback_url, rendition_height(resolved.fallback_url)))
    last_error: Exception | None = None
    for url, height in candidates:
        target = destination / video_file_name(embed.position, asset_id, height, url)
        try:
            stored = client.download(url, target, kind=VIDEO)
        except urllib.error.HTTPError as error:
            last_error = error
            continue
        _drop_superseded(destination, embed.position, asset_id, keep=stored)
        return StoredVideo(path=stored, written=True)
    raise last_error or DownloadError(f"{embed.source_url} produced no video")


def _drop_superseded(destination: Path, position: int, asset_id: str, keep: Path) -> None:
    """Remove other renditions of the same module so one module has one file."""
    if not asset_id:
        return
    for path in destination.glob(f"{position:03d}_{asset_id}_*.mp4"):
        if path != keep:
            remove_superseded(path)


def _save_external(embed: EmbedAsset, destination: Path) -> StoredVideo:
    prefix = f"{embed.position:03d}"
    try:
        from yt_dlp import YoutubeDL  # noqa: PLC0415  # optional extra, so a top-level import fails
    except ImportError as error:
        raise DownloadError(
            "external videos need the optional extra, install behance-dl[video]"
        ) from error
    with tempfile.TemporaryDirectory(prefix="behance-dl-") as staging:
        options = {
            "outtmpl": f"{prefix}_%(id)s.%(ext)s",
            "paths": {"home": str(destination), "temp": staging},
            "noplaylist": True,
            "playlist_items": "1",
            "overwrites": True,
            "quiet": True,
            "noprogress": True,
        }
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(embed.source_url, download=True)
            stored = downloaded_path(info)
    if stored is None or not stored.is_file() or stored.stat().st_size <= 0:
        raise DownloadError(f"{embed.source_url} produced no file")
    return StoredVideo(path=stored, written=True)


def downloaded_path(info: object) -> Path | None:
    """Find the file yt-dlp wrote for a video, or for the first entry of a playlist."""
    if not isinstance(info, dict):
        return None
    entries = info.get("entries")
    if isinstance(entries, (list, tuple)):
        return downloaded_path(next(iter(entries), None))
    downloads = info.get("requested_downloads")
    if isinstance(downloads, (list, tuple)) and downloads:
        first = downloads[0]
        if isinstance(first, dict) and isinstance(first.get("filepath"), str):
            return Path(first["filepath"])
    return None


def _existing_external(destination: Path, position: int) -> StoredVideo | None:
    """Find a previously downloaded external video, ignoring partial and image files."""
    for path in sorted(destination.glob(f"{position:03d}_*")):
        if path.suffix.lower() not in EXTERNAL_VIDEO_SUFFIXES:
            continue
        if path.stat().st_size > 0:
            return StoredVideo(path=path, written=False)
    return None
