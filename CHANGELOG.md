# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Ruff now selects all stable rules, with a reasoned waiver list, Google docstring conventions, and explicit formatter settings.

## [0.3.0] - 2026-11-16

### Added

- A Markdown transcript in every gallery folder, named after the folder itself: a folder such as `123456789_Sample-Gallery/` holds `123456789_Sample-Gallery.md`. It renders the page in page order with every image, the caption that belongs to it, every text block, and embed links, so the words that explain a slide are no longer lost. Images the page shows side by side stay on one line.
- An offline HTML page in every gallery folder, named after the folder too. It mirrors the layout of the project page without Behance's own interface: the canvas colour and module spacing the author chose, full width slides that fill the column, narrower images at the size the author gave them, modules that hold several images as a row sized by each image's proportions, and text modules with their formatting. It carries its own styles and needs no network.
- `GalleryPlan` carries the page's text modules and `ImageAsset` carries the caption the author wrote for it, so the renderings keep the author's words beside the images.
- A `py.typed` marker, so type checkers apply the package's annotations.
- mypy in strict mode, run over `src` and `.github/scripts` by CI.

### Changed

- `GalleryPlan` now holds `slides` instead of `images`, so a module that shows several images stays one slide. The flat image list is an `images` property derived from the slides, which keeps the download order and the reported count unchanged.
- `ImageAsset` records `display_width` and `display_height`, the size the page lays the image out at.
- Ruff now checks annotation presence, security rules, and pytest style, with documented waivers for tests.
- Development and CI now use uv, with dependencies pinned in `uv.lock`. The dev dependencies moved from the `dev` extra to a `dev` dependency group, so `pip install -e ".[dev]"` no longer installs the test and lint tools.

### Removed

- Dropped Python 3.9, 3.10, and 3.11 support, so the package requires Python 3.12 or newer.

## [0.2.0] - 2026-11-15

### Added

- `--videos` to download video modules. Behance video is resolved through Adobe's Creative Cloud player to a direct MP4 rendition, and the best rendition is chosen unless a cap is set.
- `--video-height PX` to cap the rendition height, falling back to the smallest available.
- The `video` extra, `pip install "behance-dl[video]"`, which adds yt-dlp so YouTube, Vimeo, and Dailymotion embeds download too. Without it those modules stay links and the run reports them as failed.
- A redirect policy that refuses any redirect leaving https or changing host, so both URL allowlists still describe where a request can end up.

### Changed

- `BehanceClient.download` takes a media kind. An image download now rejects video bytes, and a video download rejects image bytes.
- `--force` re-fetches videos as well as images.
- A video is named from its validated asset id and height, so a re-run can match it on disk without trusting an expiring signed URL.

### Fixed

- When the derived rendition answers 404, the fallback file is named after the rendition that actually answered instead of the one that did not.
- A playlist embed reports success once its single item is saved.

## [0.1.0] - 2026-11-14

### Added

- Download every image of a public Behance gallery from the payload embedded in the page.
- Variant selection by width with `-W`. The ranking prefers `source`, then a plain bucket, then an optimised copy, and drops single-frame stills when an animated version exists.
- `manifest.json` resume, so a re-run only fetches what is missing and a width change re-fetches the affected images.
- `embeds.json` for prototypes and video modules that are links rather than files.
- Parallel downloads, retries with backoff, atomic writes, and content type plus magic byte validation.
- The `behance-dl` console command and `python -m behance_dl`.

[Unreleased]: https://github.com/kevinkwee/behance-dl/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/kevinkwee/behance-dl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kevinkwee/behance-dl/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kevinkwee/behance-dl/releases/tag/v0.1.0
