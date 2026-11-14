"""Command line interface for the Behance gallery downloader."""

from __future__ import annotations

import argparse
import http.client
import io
import sys
import urllib.error
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .client import BehanceClient
from .errors import BehanceError
from .models import GalleryPlan
from .selection import plan_gallery
from .storage import load_saved, save_gallery
from .video import download_videos, no_reuse, reuse_downloaded


def print_plan_summary(plan: GalleryPlan) -> None:
    """Report what a gallery will produce."""
    project = plan.project
    print(f"{project.name or project.id} (id {project.id})")
    print(f"{len(plan.images)} images, {len(plan.embeds)} embeds, target {plan.destination}")
    missing = plan.expected_images - len(plan.images)
    if missing > 0:
        print(f"note: {missing} images carry no usable CDN variant")
    for embed in plan.embeds:
        if not embed.source_url:
            print(f"note: module {embed.position} is an embed without a link")


def print_plan_assets(plan: GalleryPlan) -> None:
    """List the planned images and embeds with their sources."""
    for asset in plan.images:
        print(f"  {asset.file_name} ({asset.width}px) <- {asset.url}")
    for embed in plan.embeds:
        print(f"  {embed.position:03d} embed <- {embed.source_url}")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="behance-dl",
        description="Download the images of a public Behance project gallery.",
    )
    parser.add_argument(
        "galleries",
        nargs="+",
        metavar="URL",
        help="Behance gallery URL or bare project id",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(),
        help="folder that receives one subfolder per gallery (default: current folder)",
    )
    parser.add_argument(
        "-W",
        "--max-width",
        type=positive_int,
        default=None,
        metavar="PX",
        help="largest image at or below this width in pixels, else the smallest available "
        "(default: the largest available)",
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=positive_int,
        default=4,
        help="parallel downloads (default: 4)",
    )
    parser.add_argument(
        "--attempts",
        type=positive_int,
        default=3,
        help="attempts per request before giving up (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=30.0,
        help="per-request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--videos",
        action="store_true",
        help="also download video modules, which contacts Adobe's video CDN and needs "
        'the optional extra for external hosts: pip install "behance-dl[video]"',
    )
    parser.add_argument(
        "--video-height",
        type=positive_int,
        default=None,
        metavar="PX",
        help="largest video rendition at or below this height, else the smallest available "
        "(default: the largest available)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore what is already on disk and fetch every image and video again",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be downloaded without writing files",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number") from error
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value!r} must be at least 1")
    return number


def positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from error
    if number <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} must be greater than 0")
    return number


def relax_console_encoding() -> None:
    """Keep non-Latin project names printable on consoles with a narrow encoding."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the downloads and return the process exit code."""
    args = parse_args(argv)
    relax_console_encoding()
    client = BehanceClient(timeout=args.timeout, attempts=args.attempts)
    exit_code = 0
    try:
        for gallery in args.galleries:
            try:
                plan = plan_gallery(client, gallery, args.max_width, args.output)
                print_plan_summary(plan)
                if args.dry_run:
                    print_plan_assets(plan)
                    continue
                saved = {} if args.force else load_saved(plan.destination)
                failed = save_gallery(client, plan, saved, workers=args.workers)
                if args.videos:
                    reuse = no_reuse if args.force else reuse_downloaded(args.video_height)
                    failed += download_videos(
                        client,
                        plan.embeds,
                        plan.destination,
                        max_height=args.video_height,
                        reuse=reuse,
                    )
                status = 1 if failed else 0
            except BehanceError as error:
                print(f"error: {error}", file=sys.stderr)
                status = 1
            except urllib.error.HTTPError as error:
                print(
                    f"error: {gallery}: Behance answered {error.code} {error.reason}",
                    file=sys.stderr,
                )
                status = 1
            except (OSError, http.client.HTTPException) as error:
                print(f"error: {gallery}: {error}", file=sys.stderr)
                status = 1
            exit_code = max(exit_code, status)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
