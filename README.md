# behance-dl

Download the images of a public [Behance](https://www.behance.net) project gallery.

`behance-dl` reads the project data Behance inlines in the gallery page, picks the best CDN
variant of every image, and downloads them in parallel with resume support. It keeps the
gallery order, records which variant produced each file, and logs the content it cannot
download as files (prototypes, video players) so nothing is silently lost.

No API key, account, or browser automation is required.

> Not affiliated with Behance or Adobe. Use it for offline viewing of published work, and
> respect each creator's licence before redistributing anything.

## Install

```console
pip install behance-dl
```

Requires Python 3.9 or newer. No third-party runtime dependencies.

## Usage

```console
behance-dl "https://www.behance.net/gallery/123456789/Sample-Gallery"
```

Every gallery argument can be a full Behance URL, with or without query parameters, or a
bare project id:

```console
behance-dl 123456789
behance-dl "https://www.behance.net/gallery/123456789/Sample-Gallery?l=22"
behance-dl 123456789 234567890 345678901 -o downloads
```

### Options

| Option | Meaning |
| --- | --- |
| `-o`, `--output DIR` | Folder that receives one subfolder per gallery. Default: current folder. |
| `-W`, `--max-width PX` | Largest image at or below this width, else the smallest available. Default: the largest available. |
| `-j`, `--workers N` | Parallel downloads. Default: 4. |
| `--attempts N` | Attempts per request before giving up. Default: 3. |
| `--timeout SECONDS` | Per-request timeout. Default: 30. |
| `--force` | Ignore the saved record and fetch every image again. |
| `--dry-run` | List what would be downloaded without writing anything. |
| `--version` | Print the version and exit. |

### What a gallery folder contains

```text
123456789_Sample-Gallery/
  001_0a1b2c3123456789.5f6d7e8f9a0b1.png
  002_4d5e6f7123456789.5f6d7e9a1c2d3.png
  003_8a9b0c1123456789.5f6d7eab2e3f4.jpg
  embeds.json      # prototypes and video players that are links, not files
  manifest.json    # which CDN variant produced each saved file
  project.json     # the full project payload Behance served
```

Files are prefixed with their position in the gallery, so a plain alphabetical listing
follows the project order. The extension is taken from the file's magic bytes, because
Behance's CDN sometimes serves JPEG data under a `.png` name.

`embeds.json` records modules that cannot be downloaded as images, such as Figma prototypes
and Adobe video players, with their source URL, caption and dimensions.

## Re-running, resume and width changes

`manifest.json` records the URL each file came from. A re-run only fetches what is missing,
and a run with a different `-W` re-fetches the affected images instead of leaving files at
the old size. An interrupted run keeps whatever already landed, so `Ctrl+C` followed by the
same command continues where it stopped.

Delete `manifest.json` (or pass `--force`) to fetch everything again.

## How it works

1. `GET https://www.behance.net/gallery/{id}/gallery`. Behance answers 404 for an id with no
   trailing slug and ignores the slug itself, so any slug works.
2. Behance answers 403 with a cookie challenge
   (`document.cookie = "js_challenge_value=..."; location.reload()`). The client sets the
   cookie and retries once. This is not a CAPTCHA and needs no credentials.
3. The project payload is read from `<script id="beconfig-store_state">`. It lists every
   module and every CDN variant of each image with its pixel width.
4. Variants are filtered and ranked: WebP copies are skipped so the saved file matches the
   original format, `_still` buckets are dropped when an animated variant exists (a still
   bucket holds only the first frame of a GIF), and equal widths prefer `source` over a
   plain bucket over an `_opt_` copy.
5. Images are downloaded in a thread pool, each to a `.part` file that is verified against
   `Content-Length`, checked for an image content type and real magic bytes, then renamed
   into place.

`MediaCollectionModule` carousels are expanded into one file per component. Only URLs on
`https://*.behance.net` are ever requested, so a tampered payload cannot point the tool at
a local file or a third-party host.

## Limitations

- Only public projects. Private, removed, or login-gated projects report a clear error.
- Images only. Prototypes and video modules are recorded as links in `embeds.json`.
- Behance can change its page format at any time; the payload shape is checked and a
  mismatch is reported as an error instead of producing an empty folder.

## Development

```console
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT. See [LICENSE](LICENSE).
