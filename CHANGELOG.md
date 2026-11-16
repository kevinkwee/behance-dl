# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `captions.md` in a gallery folder when the project carries author-written prose. It renders the page in page order with every image, the caption that belongs to it, every text block, and embed links, so the words that explain a slide are no longer lost.
- A `py.typed` marker, so type checkers apply the package's annotations.
- mypy in strict mode, run over `src` and `.github/scripts` by CI.

### Changed

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

[Unreleased]: https://github.com/kevinkwee/behance-dl/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kevinkwee/behance-dl/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kevinkwee/behance-dl/releases/tag/v0.1.0
