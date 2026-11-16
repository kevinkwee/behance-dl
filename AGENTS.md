# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

`behance-dl` is a command line downloader for public Behance project galleries, published to PyPI as `behance-dl` with the import package `behance_dl`.

It reads the project payload Behance inlines in a gallery page (`beconfig-store_state`), chooses one CDN variant per image, and downloads the files concurrently with resume support. With `--videos` it also resolves Behance video modules to direct MP4 renditions, and hands external embeds to the optional yt-dlp extra. It keeps gallery order, records which variant produced each file in `manifest.json`, records prototypes and video modules as links in `embeds.json`, and renders the page as a Markdown transcript named after the gallery folder.

Technology stack: Python 3.12 or newer, standard library only at runtime, Hatchling as the PEP 517 backend, invoked by `uv build`, mypy for static types, pytest for tests, Ruff for lint and format, GitHub Actions for CI and publishing.

Key behaviours that must not regress:

- Gallery pages answer 404 for `/gallery/{id}` with no slug, so requests use `/gallery/{id}/gallery`.
- Behance answers 403 with a cookie challenge. The client sets `js_challenge_value` and retries once with a fresh `Request`, because a reused request keeps the stale `Cookie` header.
- Variant ranking prefers `source`, then a plain bucket, then an `_opt_` copy, and drops `_still` buckets whenever an animated variant exists. A still bucket holds only the first frame of an animated image.
- Only `https` URLs on `behance.net` or a `.behance.net` subdomain may be requested. The page payload is untrusted input.
- The CDN sometimes serves JPEG bytes under a `.png` name, so the saved extension comes from the file's magic bytes.
- Behance video is an Adobe Creative Cloud player iframe with no media in the embed itself. The player page lists the stream sources, and each MP4 rendition is directly fetchable with the signed token from the master playlist.

## Prerequisites

- Python 3.12 or newer. See Language and Runtime Constraints for what the floor rules out.
- `uv`, which provides the environment, the lockfile, and the build command.
- No external services, credentials, or API keys. Behance is accessed anonymously.
- Optional: `uv sync --extra video` adds yt-dlp so external video hosts can be downloaded. A later plain `uv sync` removes it again.
- Windows is the primary development platform, and CI also runs Linux and macOS.

## Core Philosophy

### Trade-off Priority (when conflicts arise)

1. **Correctness**: the download matches the gallery and the record stays truthful.
2. **Simplicity and readability**: one small function per job, standard library first.
3. **Testability**: network access sits behind `BehanceClient`, so tests use fakes.
4. **Performance**: parallel downloads and streaming transfers, without speculative optimisation.
5. **Abstraction and reuse**: extract only when duplication is already costing more than a shared helper.

### Ground Rules

- Read and understand the existing module before changing it, and preserve the behaviours listed in Project Overview.
- If a requirement is ambiguous, ask before writing code.
- Do not overengineer. Build for today's requirements.
- A change to `BehanceClient`, the payload parsing, or the manifest format affects every command, so verify the touched paths end to end.

## Design Principles

### SOLID

| Principle | Rule | Common Mistake |
|-----------|------|----------------|
| **SRP** (Single Responsibility) | Each module has one axis of change. `client` speaks HTTP, `gallery` parses payloads, `selection` ranks variants, `storage` writes files, `cli` parses arguments and reports. | Putting reporting inside the save step, or network calls inside selection. |
| **OCP** (Open/Closed) | Add a new module type by extending the dispatch in `gallery.image_sources` and `gallery.embed_assets`. | Scattering module-type checks across several functions. |
| **LSP** (Liskov Substitution) | A fake client used in tests must honour the same contract as `BehanceClient`. | A fake that returns bodies the real client would reject. |
| **ISP** (Interface Segregation) | Fakes implement only `get_text` and `download`, which is all the planning and saving code uses. | A test double exposing unrelated helpers. |
| **DIP** (Dependency Inversion) | `plan_gallery` and `save_gallery` accept a client object rather than constructing one. | Constructing `BehanceClient` deep inside planning code. |

### DRY, KISS, YAGNI

- One rule lives in one place. The Behance host rule lives in `gallery.is_behance_host`, and the file-name rule lives in `naming.safe_name`.
- Prefer duplication over a wrong abstraction. Two similar-looking expressions with different purposes stay separate.
- Standard library before any dependency. Runtime dependencies stay at zero unless a feature genuinely needs one.
- No speculative options, flags, or abstractions.

## Language and Runtime Constraints

The floor is Python 3.12, so the code cannot use features added in 3.13 or later, such as `typing.TypeIs`, `typing.ReadOnly`, and `copy.replace`.

Everything through 3.12 is available: `match`/`case`, PEP 604 unions, builtin generics, `datetime.UTC`, `tomllib`, `itertools.batched`, and exception groups.

Keep `from __future__ import annotations` at the top of every module, so annotations stay unevaluated and forward references need no quoting.

## Code Quality

### Linting and Formatting

- Ruff handles both linting and formatting, configured in `pyproject.toml` at line length 100 with `target-version = "py312"`.
- The selection covers style, imports, modernisation, bugbear, simplification, pathlib, return conventions (`RET`), Ruff-specific rules (`RUF`), annotations (`ANN`), security (`S`), and pytest style (`PT`).
- After changing files, run `uv run ruff format .`, `uv run ruff check .`, and `uv run mypy`. All three must be clean before a change is complete.
- `tests/*` waives only `S101`, because asserting is a test's job, and `ANN001`, because pytest injects fixtures that the test does not annotate.
- `tests/conftest.py` is the shared test double module, registered as first-party for import sorting.

#### Handling a Linter Violation

Follow this order and stop at the first step that fits.

1. **Fix the code.** This is almost always the right answer.
2. **Configure the rule** in `pyproject.toml` when its defaults do not fit the project, and comment why.
3. **Per-line `noqa`** with the specific rule codes and a short reason, only for a genuine false positive or an unavoidable pattern. Never a bare `# noqa`.
4. **Block-level suppression** with `# ruff: disable[RULE]` and `# ruff: enable[RULE]` for a contiguous run of legitimate violations, always re-enabled.
5. **Narrow per-file ignore** in `[tool.ruff.lint.per-file-ignores]` when a whole file or directory legitimately violates a rule, as `tests/*` does.

### Naming

- Functions start with a verb, classes are nouns, and booleans read as a yes/no question.
- No generic names such as `data`, `result`, `obj`, `thing`, `temp`, or `utils`.
- No abbreviations beyond universally understood ones. `url` inside a tuple unpacking may stay lowercase when it names the element, and prose uses `URL`.
- One concept keeps one name across modules. A saved image is a `SavedImage` in the record, an `ImageAsset` when planned, and a `StoredImage` when written.

### Strong Typing

- Annotate every public function's parameters and return value. `uv run mypy` enforces this over `src` and `.github/scripts` with `strict = true`, and CI runs it.
- Avoid `Any` except where a JSON payload is genuinely untyped, and narrow it immediately with `isinstance` checks.
- Do not cast to `Any` to make an error disappear. A cast to a concrete type is allowed where a signature outside this project is imprecise, and needs a comment saying why.
- A `# type: ignore` carries the same obligations as a `# noqa`: the specific error code and a reason.
- The package ships `src/behance_dl/py.typed`, so every public annotation is part of the published API and a change to one is semver-visible. `tests/test_packaging.py` guards the marker.
- Tests follow the `tests/*` waiver. Return annotations still apply.

### Immutability

- Dataclasses are frozen. Return new objects instead of mutating inputs.
- Never expose a mutable internal collection. `GalleryProject.modules` is a tuple.

### Early Returns and Guard Clauses

- Put the happy path at the lowest nesting level and return early for the failure case.
- Reduce nesting by inverting a condition, not by adding another level.

### No Magic Values

- Extract a repeated number or string into a named module constant next to where it is used, such as `RETRYABLE_STATUS`, `TRANSFER_BLOCK_SIZE`, `MAX_BACKOFF_SECONDS`, and `MANIFEST_NAME`.
- Name the constant after what the value means, not how it is consumed.
- A literal that is self-evident, such as a slice offset in a format check, may stay inline.

### Comments and Docstrings

- Write a comment only when it explains why, never what.
- A docstring states the unit's purpose without restating its signature or parameters.
- Comments and docstrings must make sense to a cold reader. No references to reviews, tickets, or conversations.
- Never use em-dashes or en-dashes, and never use a hyphen as a clause separator. End the sentence or use a comma.

### Functions

- One job per function. No boolean parameter that switches behaviour.
- Pass a callback rather than a flag when the caller needs to react to per-item results, as `download_images` does with `on_saved`.
- Put a policy in the caller. `download_videos` takes a `reuse` lookup rather than a `force` flag, so the CLI owns whether existing files are trusted.

### Performance

- Stream a response body straight to disk in `TRANSFER_BLOCK_SIZE` blocks. Never read a whole image into memory, because originals reach tens of megabytes.
- Bound concurrency with `--workers`. More threads stop helping once Behance rate limits.
- Back off on 429 and 5xx, and never retry a 4xx that will fail again.
- Do not add caching, connection pools, or async IO without a measured need.

### Output Conventions

- Progress and plans go to standard output. Warnings and errors go to standard error.
- Exit codes: `0` success, `1` a gallery failed, `2` invalid arguments, `130` interrupted.
- Never log or print credentials, and there are none to print.

## Architecture

### Module Layout

| Module | Responsibility |
|--------|----------------|
| `client.py` | HTTP session, cookie challenge, retries, atomic media transfers. |
| `gallery.py` | Behance host and URL rules, gallery id parsing, payload parsing, module walking. |
| `selection.py` | Bucket ranking, variant selection, building a `GalleryPlan`. |
| `transcript.py` | Markdown rendering of the page: text blocks, captions, and embed links. |
| `storage.py` | Manifest reading and writing, parallel downloads, metadata files. |
| `models.py` | Frozen dataclasses shared across modules. |
| `naming.py` | File-name safety rules. |
| `video.py` | Adobe player resolution, rendition selection, external video downloads. |
| `errors.py` | `BehanceError`, `GalleryError`, `DownloadError`. |
| `cli.py` | Argument parsing, reporting, exit codes. |

### Separation of Concerns

- `selection.py` works on plain payload dictionaries and stays pure, so ranking is testable without IO.
- Side effects live at the edges. `client.py` speaks HTTP and `storage.py` touches the filesystem, and neither makes a ranking or naming decision.
- Data crosses a boundary as a frozen dataclass from `models.py`, never as a raw response object.

### Layer Rules

- Network access happens only in `client.py`. `video.py` resolves URLs and then calls that client, and yt-dlp is the one deliberate exception because the external extra owns its own transfers.
- Filesystem writes happen only in `storage.py`.
- Selection works on plain payload dictionaries and never performs IO.
- Errors cross module boundaries as `BehanceError` subclasses, and `cli.main` is the single place that converts them to exit codes.

### Dependency Injection

- Pass the client into `plan_gallery` and `save_gallery` instead of building one there, so a fake replaces the network in tests.
- Keep the composition root in `cli.main`. It is the only place that constructs a `BehanceClient`.
- Do not inject a pure helper such as `naming.safe_name`. Call it directly.

### Dependency Direction

`cli` depends on `selection`, `storage`, and `video`. `selection` depends on `gallery` and `models`. `storage` depends on `client`, `models`, `naming`, and `transcript`. `transcript` depends on `models`. `gallery` depends on `client` and `models`. `video` depends on `client`, `models`, `errors`, `naming`, and `storage`. `models` and `naming` depend on nothing local. No module imports `cli`, and no cycles are allowed.

## File Structure

### Avoid Over-Engineering

- Split a module when it gains a second reason to change, not when it gains length. `storage.py` holds both downloads and the manifest because both answer what is on disk.
- Keep together what changes together.

### File Naming

- Never create `utils.py`, `helpers.py`, `misc.py`, `common.py`, or `shared.py`.
- Name a module after its role: `client`, `gallery`, `selection`, `storage`, `naming`, `errors`, `cli`.
- Add a module to the Module Layout table in the same change that creates it.

## Error Handling

- Define domain errors in `errors.py`. Do not raise bare `Exception` or `RuntimeError` directly.
- Convert untrusted payload shapes into `GalleryError` with enough context to identify the gallery.
- A single failed image must not abort a gallery, and a single failed gallery must not abort a batch.
- An interruption must leave the record truthful, so record each image as soon as it lands.
- Never fail a run because cleanup or bookkeeping failed. Warn and continue.

### Exception Chaining

| Form | Use when |
|------|----------|
| `raise NewError(...) from error` | Translating a low-level failure into a domain error, such as a payload shape error becoming `GalleryError`. The cause stays attached. |
| `raise NewError(...) from None` | The cause would leak an internal detail the caller cannot act on. |
| Bare `raise` | Re-raising the same exception inside an `except` block, which is the norm for a cleanup path. |

- Inside an `except` block, choose `from error` or `from None` deliberately. Implicit chaining adds a second traceback nobody reads.
- Do not chain and also paste the cause into the message, because that prints the cause twice.

## Security

### Secure by Design

- Deny by default. The image URL allowlist admits only `https` on Behance hosts, and anything else is dropped rather than fetched.
- Fail closed. An unparseable or unexpected payload raises `GalleryError` and produces no files.
- Refuse a redirect that leaves https or changes host. `client.SameHostRedirects` enforces that rule, so the allowlists still describe where a request can end up.
- Keep the surface minimal. The tool sends one request per page, one per image, and writes only inside the gallery folder.
- Threat-model the page payload whenever parsing changes. An attacker controls every value in it, including image URLs, module types, and file names.

### Input Validation and Injection

- Treat every value in the page payload as untrusted.
- Fetch an embed link only when `--videos` was passed, and only through the matching allowlist.
- Two purpose-scoped allowlists exist. Images may come only from `https` URLs on `behance.net` or a `.behance.net` subdomain, enforced in `gallery.is_behance_url`. Video may come only from `https://www-ccv.adobe.io` player pages and `https://cdn-prod-ccv.adobe.com` media, enforced in `video.is_ccv_player_url` and `video.is_ccv_media_url`. Never widen one to cover the other.
- Never build a file path from raw remote text. Pass names through `naming.safe_name`, and validate recorded names with `naming.is_plain_file_name`.
- A recorded path must stay inside the gallery folder and share the planned stem.
- Page prose is untrusted too. `transcript.py` escapes Markdown metacharacters, so a caption cannot add raw HTML or an image, and it turns an author's anchor into Markdown only when the target is an http or https URL with a host.
- The single `# noqa: S310` in `client.py` stays justified only while every URL is built on the `BEHANCE_ORIGIN` constant, checked by the two allowlists above, or derived from an allowlisted playlist by `video.build_rendition_url`, and `SameHostRedirects` enforces the redirect rule above. Remove the suppression if any of those controls goes away.
- Check the content type and the magic bytes against the requested media kind. An image download rejects MP4, AVIF, and HEIC bytes, and a video download rejects PNG and HTML bytes. A mismatch leaves no file and no `.part` behind.

### Secrets Management

- Never commit credentials, tokens, or API keys.
- Never place a secret in a workflow file, a test fixture, or a log line.

### Dependencies and Supply Chain

- Runtime dependencies stay at zero. The only optional dependency is `yt-dlp`, isolated in the `video` extra, and it must never become a hard requirement.
- Development dependencies live in the `dev` dependency group and are pinned in `uv.lock`. CI installs them with `uv sync --locked`.
- Do not add a dependency with a known vulnerability that affects this code.

### Security Tests

- Every control carries an adversarial test: a `file://` URL, a foreign host, a look-alike domain, a traversal file name, a manifest entry pointing at `project.json`, a non-image content type, a truncated body, an escaped angle bracket in a caption, a `javascript:` and a `file:` link target, and a destination that tries to close the Markdown link.
- Assert the side effect, not only the error. A rejected image must leave no file and no `.part` behind.
- Use synthetic payloads. Never commit a real creator's project data as a fixture.

## Testing

> **Test code is production code.** It receives the same care, review, and quality standards.

### Core Principles

- Tests must never touch the network. Use the fakes in `tests/conftest.py`, or stub `_opener` on `BehanceClient`.
- Follow Arrange-Act-Assert, with one act and one logical assertion per test.
- Tests must be independent, deterministic, and order-agnostic.
- Pin specific exception types in `pytest.raises`.
- Test behaviour through public functions. Stubbing `client._opener` is the accepted exception, because the cookie jar has no other seam.
- Add a regression test for every bug fixed.

### How to Run Tests

```powershell
uv sync
uv run pytest
uv run mypy
uv run ruff check .
uv run ruff format --check .
uv build
```

### Test Naming

- pytest collects `test_` functions. Use `test_[subject]_[aspect]` as the default, for example `test_still_bucket_dropped_when_animated_variant_exists`.
- Use `test_[behaviour]` only when splitting into subject and aspect would be artificial.
- Do not encode assertion types or fixture names in a test name.

### Tests Must Also Challenge the Code

- Happy paths first, then adversarial cases: `None`, empty strings, empty lists, wrong types, missing keys, and widths exactly at a boundary.
- Write a test from the requirement, not from the current implementation. A test that mirrors the code finds no bugs.
- When a test fails, decide whether the code or the test is wrong before editing either.

### Test File Rules

- One file per module under test: `test_client.py`, `test_gallery.py`, `test_selection.py`, `test_transcript.py`, `test_storage.py`, `test_video.py`, `test_naming.py`, `test_cli.py`.
- `test_packaging.py` asserts the `py.typed` marker exists.
- Shared doubles and payload builders live in `tests/conftest.py`, and test-local helpers stay in the test module that uses them.

### Coverage

- **Minimum acceptable: 85%**, measured with branch coverage. The suite measured 94% at the 0.1.0 release.
- Run `uv run pytest --cov=behance_dl --cov-report=term-missing` and report the result for the touched modules.

### All Created Tests MUST Pass

- Every test you create or modify must pass, with zero failures and zero skips.
- Never disable, skip, or delete a test to hide a failure. Fix the code first when the code is wrong.
- When a test fails, decide whether the code or the test is wrong before editing either.

### What NOT to Test

- Trivial properties that only return a stored field.
- Implementation detail such as call order, private helpers, or the exact text of a log line.
- Coverage padding with assertions that cannot fail.

### Anti-Patterns (Forbidden)

| Pattern | Problem |
|---------|---------|
| **The Liar** | Passes without verifying the behaviour it claims to test |
| **The Mirror** | Asserts exactly what the code does, so it catches no bug |
| **The Giant** | Long setup, several acts, dozens of assertions. Split it |
| **The Mockery** | So many doubles that the test only checks the doubles |
| **The Inspector** | Coupled to private detail and breaks on any refactor |
| **The Chain Gang** | Depends on execution order or shares mutable state |
| **The Flaky** | Passes and fails with no code change |

## Versioning

- The version lives in `src/behance_dl/__init__.py` and Hatchling reads it from there, so bump it in one place.
- Every release must come from a working tree with passing tests, passing lint, passing types, and no uncommitted changes.

## Code Review

### Priority (blockers first)

1. **Security**: untrusted URLs, paths, and payload shapes
2. **Data integrity**: the manifest must never claim a file that is not on disk
3. **DRY**: one rule, one place
4. **Architecture**: layer rules and dependency direction
5. **Code quality**: types, naming, error handling
6. **Testing**: happy path and adversarial coverage
7. **Documentation**: README and this file in sync with the code

### Review Questions for Tests

1. Are there both happy path and adversarial tests?
2. Would these tests catch a regression if someone broke the logic?
3. Which failure mode is still untested?
4. If a line of ranking or download logic were deleted, would a test fail?

## Documentation

- Update `README.md` when user-facing behaviour, an option, or the output layout changes.
- Update this file when a module, an invariant, or a recorded command changes.
- Record every user-facing change under `CHANGELOG.md` -> `## [Unreleased]`, and never rewrite a released section.
- Both files describe the current code. Never narrate history in them.

## Key Concepts

1. **One page per gallery.** `GET /gallery/{id}/gallery` returns HTML carrying the whole project in `beconfig-store_state`. Everything downstream derives from that payload.
2. **Untrusted payload.** Every value in it is attacker-controlled. Ranking reads only allowlisted URLs, and every file name passes through `naming.safe_name`.
3. **Variant identity.** A CDN file name repeats across buckets, so the URL is the identity. `manifest.json` records the URL per saved file, which is why a width change refetches.
4. **Atomic writes.** An image lands in a `.part` file, is checked for content type, magic bytes, and length, then renamed into place. The record is written after each image, so an interrupt stays truthful.
5. **Video is a player, not a file.** A video module is an Adobe CCV iframe that carries no media. Resolving it means fetching the player page, reading the master playlist for the rendition heights, then fetching `<asset>_<height>.mp4` with the playlist token. That token expires, so it is never resume identity. A re-run reuses an existing `<position>_<asset>_*.mp4` without touching the network, unless the caller chose not to or the file is taller than the requested cap.
6. **Exit codes.** `cli.main` maps a failure to `0`, `1`, `2`, or `130` and is the only place that does.

## Rule of Thumb

**When in doubt: correctness over cleverness, one honest record over a silent skip, and a clear error over a wrong file on disk.**
