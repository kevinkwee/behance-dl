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

Requires Python 3.12 or newer. No third-party runtime dependencies.

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
| `--videos` | Also download video modules. Contacts Adobe's video CDN, and needs the optional extra for external hosts. |
| `--video-height PX` | Largest video rendition at or below this height, else the smallest available. Default: the largest available. |
| `--force` | Ignore what is already on disk and fetch every image and video again. |
| `--dry-run` | List what would be downloaded without writing anything. |
| `--version` | Print the version and exit. |

### What a gallery folder contains

```text
123456789_Sample-Gallery/
  001_0a1b2c3123456789.5f6d7e8f9a0b1.png
  002_4d5e6f7123456789.5f6d7e9a1c2d3.png
  003_8a9b0c1123456789.5f6d7eab2e3f4.jpg
  005_ExampleAsset1_720.mp4      # only with --videos
  123456789_Sample-Gallery.md    # the whole page in Markdown, in page order
  123456789_Sample-Gallery.html  # the same page as an offline web page
  embeds.json                    # prototypes, and video modules as links
  manifest.json                  # which CDN variant produced each saved image
  project.json                   # the full project payload Behance served
```

Files are prefixed with their position in the gallery, so a plain alphabetical listing
follows the project order. The extension is taken from the file's magic bytes, because
Behance's CDN sometimes serves JPEG data under a `.png` name.

`embeds.json` records modules that are links rather than files, such as Figma prototypes and
video modules, with their source URL, caption and dimensions. It is always written, so the
original page stays reconstructable even when the media itself was downloaded.

The folder's `.md` file, named after the folder itself, renders the whole page in page
order. Every image appears with the caption that belongs to it, the text blocks stay where
the author placed them, and a module that shows several images in one row becomes one line
of images, so the slides that belong together read together. An image link points at the
file's saved name, so a JPEG served as `.png` links to the `.jpg` on disk. It is written
for every gallery, so even a project without captions leaves a readable index of its
images.

The `.html` file is the same page rendered as a standalone web page that opens without a
network.
It follows the layout the author chose on Behance: the canvas colour and the spacing
between modules come from the page's own style, a full width slide fills the column, a
narrower image keeps the size the author gave it, and a module that holds several images is
a row sized by each image's proportions. Text modules keep their alignment, colours and
sizes, and embedded prototypes and videos become links. The document carries its own
styles and reads every image from the same folder, so it needs no fonts or scripts from
elsewhere.

## Re-running, resume and width changes

`manifest.json` records the URL each image came from. A re-run only fetches what is missing,
and a run with a different `-W` re-fetches the affected images instead of leaving files at
the old size. An interrupted run keeps whatever already landed, so `Ctrl+C` followed by the
same command continues where it stopped.

Delete `manifest.json` to re-fetch every image. Videos are not recorded there, because
their signed URLs expire. Behance videos are matched on disk by position and asset id, and
external ones by position.
`--force` re-fetches both images and videos.

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

## Videos

Pass `--videos` to download video modules too. Behance hosts video through Adobe's Creative
Cloud player: the iframe carries no media, but the player page lists the renditions and the
CDN serves direct MP4 files. The downloader reads the master playlist, picks the best
rendition (or the best one at or below `--video-height`, else the smallest available), and
saves it as `005_<asset>_<height>.mp4`.

External hosts such as YouTube and Vimeo need the optional extra:

```console
pip install "behance-dl[video]"
```

Without it, each external module is reported as failed and the run exits 1, while the
module still stays a link in `embeds.json`. A rejected external download never leaves a
partial file in the gallery folder. Interactive embeds such as Figma prototypes are not video and always stay links.

This is opt-in because it contacts a second set of hosts beyond Behance:
`www-ccv.adobe.io` for the player page and `cdn-prod-ccv.adobe.com` for the media.

## Limitations

- Only public projects. Private, removed, or login-gated projects report a clear error.
- Images by default. Video needs `--videos`, and external hosts additionally need the
  `video` extra. Figma prototypes cannot be downloaded because they are rendered live, not
  encoded as media.
- Behance can change its page format at any time; the payload shape is checked and a
  mismatch is reported as an error instead of producing an empty folder.

## Development

Requires [uv](https://docs.astral.sh/uv/). Run `uv sync` to install the locked development
environment.

```console
uv sync
uv run pytest
uv run mypy
uv run ruff check .
uv run ruff format --check .
uv build
```

## Changelog

Release notes live in [CHANGELOG.md](CHANGELOG.md), and every tagged version has a
[GitHub release](https://github.com/kevinkwee/behance-dl/releases).

## License

MIT. See [LICENSE](LICENSE).
