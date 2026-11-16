"""Download the images of a public Behance project gallery.

Behance inlines the whole project into the gallery page: every module plus every CDN
variant of each image with its pixel width. The downloader reads that payload, picks one
variant per image, and fetches the files concurrently. The payload itself is kept in
project.json, embeds such as prototypes and videos go to embeds.json because they are not
images, and manifest.json records which variant produced each saved file so a re-run only
fetches what is missing.

Files are meant for offline viewing of published work. Respect the creator's licence and
Behance's terms before redistributing anything.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.3.0"
