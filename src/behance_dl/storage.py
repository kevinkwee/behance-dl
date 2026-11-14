"""Writing gallery files and recording which variant produced each saved image."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .client import BehanceClient
from .models import GalleryPlan, ImageAsset, SavedImage, StoredImage
from .naming import is_plain_file_name

MANIFEST_NAME = "manifest.json"


def load_saved(destination: Path) -> dict[str, SavedImage]:
    """Read the record of files already written to a gallery folder."""
    manifest = destination / MANIFEST_NAME
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        print(f"warning: ignoring unreadable {manifest}: {error}", file=sys.stderr)
        return {}
    if not isinstance(entries, dict):
        print(f"warning: ignoring {manifest}: it does not hold an object", file=sys.stderr)
        return {}
    saved: dict[str, SavedImage] = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        url, path = entry.get("url"), entry.get("path")
        if isinstance(url, str) and isinstance(path, str) and is_recorded_name(name, path):
            saved[name] = SavedImage(url=url, path=path)
    return saved


def is_recorded_name(name: str, path: str) -> bool:
    """Report whether a recorded file is a plain file name sharing the planned stem."""
    return (
        is_plain_file_name(name) and is_plain_file_name(path) and Path(path).stem == Path(name).stem
    )


def save_gallery(
    client: BehanceClient,
    plan: GalleryPlan,
    saved: dict[str, SavedImage],
    *,
    workers: int,
) -> int:
    """Write one gallery's metadata and images, returning how many images failed."""
    destination = plan.destination
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "project.json", plan.project.payload)
    if plan.embeds:
        write_json(destination / "embeds.json", [asdict(embed) for embed in plan.embeds])

    record = dict(saved)

    def remember(name: str, entry: SavedImage) -> None:
        previous = record.get(name)
        if previous is not None and previous.path != entry.path:
            remove_superseded(destination / previous.path)
        record[name] = entry
        try:
            write_json(
                destination / MANIFEST_NAME,
                {key: asdict(value) for key, value in record.items()},
            )
        except OSError as error:
            print(f"warning: could not record {name} in {MANIFEST_NAME}: {error}", file=sys.stderr)

    failed = download_images(
        client,
        plan.images,
        destination,
        saved,
        workers=workers,
        on_saved=remember,
    )
    if failed:
        print(f"{failed} of {len(plan.images)} images failed", file=sys.stderr)
    else:
        print(f"done: {len(plan.images)} images in {destination}")
    return failed


def download_images(
    client: BehanceClient,
    assets: Sequence[ImageAsset],
    destination: Path,
    saved: dict[str, SavedImage],
    *,
    workers: int,
    on_saved: Callable[[str, SavedImage], None],
) -> int:
    """Download the assets that are missing, reporting each result and returning failures."""
    total = len(assets)
    failed = 0
    reported: set[str] = set()
    pool = ThreadPoolExecutor(max_workers=workers)
    pending: dict[Future[StoredImage], ImageAsset] = {}
    try:
        pending = {
            pool.submit(save_image, client, asset, destination, saved.get(asset.file_name)): asset
            for asset in assets
        }
        for completed, future in enumerate(as_completed(pending), start=1):
            asset = pending[future]
            name = asset.file_name
            try:
                stored = future.result()
            # A single failed image must not abort the remaining ones.
            except Exception as error:
                failed += 1
                print(f"[{completed}/{total}] failed {name}: {error}", file=sys.stderr)
                continue
            on_saved(name, SavedImage(url=asset.url, path=stored.path.name))
            reported.add(name)
            status = "saved " if stored.written else "exists"
            print(f"[{completed}/{total}] {status} {stored.path.name}")
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        pool.shutdown(wait=True)
        report_finished(pending, reported, on_saved)
    return failed


def report_finished(
    pending: dict[Future[StoredImage], ImageAsset],
    reported: set[str],
    on_saved: Callable[[str, SavedImage], None],
) -> None:
    """Record downloads that finished without being reported, such as after an interrupt."""
    for future, asset in pending.items():
        name = asset.file_name
        if name in reported or future.cancelled() or not future.done():
            continue
        if future.exception() is not None:
            continue
        stored = future.result()
        on_saved(name, SavedImage(url=asset.url, path=stored.path.name))
        reported.add(name)


def save_image(
    client: BehanceClient,
    asset: ImageAsset,
    directory: Path,
    recorded: SavedImage | None,
) -> StoredImage:
    """Reuse a recorded download or fetch the asset again."""
    if recorded is not None and recorded.url == asset.url:
        existing = directory / recorded.path
        if existing.is_file() and existing.stat().st_size > 0:
            return StoredImage(path=existing, written=False)
    return StoredImage(path=client.download(asset.url, directory / asset.file_name), written=True)


def remove_superseded(path: Path) -> None:
    """Drop a file a new download replaced, warning instead of failing that download."""
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        print(f"warning: could not remove {path}: {error}", file=sys.stderr)


def write_json(path: Path, data: Any) -> None:
    """Write JSON so a reader never sees a half-written file."""
    temporary = path.with_name(path.name + ".part")
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
