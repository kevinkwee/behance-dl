"""Rendering a project page as a Markdown transcript that keeps its captions."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Mapping
from html.parser import HTMLParser
from operator import itemgetter

from .models import EmbedAsset, GalleryPlan, ImageAsset

CAPTIONS_NAME = "captions.md"

_BLOCK_TAGS = frozenset({"div", "p", "li"})
_LINK_SCHEMES = frozenset({"http", "https"})
_SAFE_LINK_CHARACTERS = ":/?#@!$&'*+,;=%~"
_MARKDOWN_SPECIALS = frozenset("\\`*_{}[]<>&#!|~")
_LINE_START_BULLET = re.compile(r"^([ \t]*)([-+])(?=\s|$)", re.MULTILINE)
_LINE_START_NUMBER = re.compile(r"^([ \t]*)(\d{1,9})([.)])(?=\s|$)", re.MULTILINE)
_LINE_START_SETEXT = re.compile(r"^([=-]+)[ \t]*$", re.MULTILINE)
_BLANK_RUNS = re.compile(r"\n{3,}")
_CONTROL_OR_SPACE = re.compile(r"[\s\x00-\x1f\x7f]")


def escape_markdown(text: str) -> str:
    """Keep payload text from forming a Markdown link, an image, or raw HTML."""
    return "".join(
        f"\\{character}" if character in _MARKDOWN_SPECIALS else character for character in text
    )


def escape_line_starts(text: str) -> str:
    """Keep a payload line from starting a list or a setext heading."""
    text = _LINE_START_BULLET.sub(r"\1\\\2", text)
    text = _LINE_START_NUMBER.sub(r"\1\2\\\3", text)
    return _LINE_START_SETEXT.sub(r"\\\1", text)


def safe_link_target(url: str) -> str | None:
    """Return the percent-encoded target for an http or https address with a host, else None."""
    candidate = url.strip()
    if _CONTROL_OR_SPACE.search(candidate):
        return None
    try:
        parts = urllib.parse.urlsplit(candidate)
        if parts.scheme not in _LINK_SCHEMES or not parts.netloc:
            return None
        return urllib.parse.quote(candidate, safe=_SAFE_LINK_CHARACTERS)
    except ValueError:
        # An address a URL parser rejects is not a link, whatever the caption wanted.
        return None


class MarkdownWriter(HTMLParser):
    """Turn the small HTML subset Behance stores in page prose into Markdown."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._href = ""
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._break()
        elif tag in _BLOCK_TAGS:
            self._boundary()
        elif tag == "a":
            self._flush_link()
            self._href = dict(attrs).get("href") or ""
            self._label = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._boundary()
        elif tag == "a":
            self._flush_link()

    def handle_data(self, data: str) -> None:
        if self._href:
            self._label.append(data)
        else:
            self._parts.append(escape_markdown(data))

    def render(self) -> str:
        """Return the rendered Markdown with runs of blank lines collapsed."""
        self._flush_link()
        lines = [line.strip() for line in "".join(self._parts).split("\n")]
        text = _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()
        return escape_line_starts(text)

    def _break(self) -> None:
        if self._href:
            self._label.append(" ")
        else:
            self._parts.append("\n")

    def _boundary(self) -> None:
        raw = "".join(self._label)
        if raw.strip():
            self._flush_link()
        elif raw:
            # Keep only the single space a link spreads across a block, so the list cannot grow.
            self._label = [raw[:1]]
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    def _flush_link(self) -> None:
        href, self._href = self._href, ""
        raw = "".join(self._label)
        self._label = []
        if not href:
            return
        label = escape_markdown(" ".join(raw.split()))
        if not label:
            if raw and self._parts and not self._parts[-1].endswith("\n"):
                self._parts.append(" ")
            return
        target = safe_link_target(href)
        body = f"[{label}]({target})" if target is not None else label
        leading = " " if raw[:1].isspace() else ""
        trailing = " " if raw[-1:].isspace() else ""
        self._parts.append(f"{leading}{body}{trailing}")


def markdown_text(markup: str) -> str:
    """Render the HTML Behance stores for a caption or a text block as Markdown."""
    writer = MarkdownWriter()
    try:
        writer.feed(markup)
        writer.close()
        return writer.render()
    except (AssertionError, ValueError):
        # An interpreter can refuse markup or a character reference, and the words still matter.
        return escape_line_starts(escape_markdown(markup))


def image_markdown(asset: ImageAsset, saved_names: Mapping[str, str]) -> str:
    """Render one image reference with the caption the author placed under it."""
    name = asset.file_name
    parts = [f"![{name}]({saved_names.get(name, name)})"]
    caption = markdown_text(asset.caption)
    if caption:
        parts.append(caption)
    return "\n\n".join(parts)


def embed_markdown(embed: EmbedAsset) -> str:
    """Render an embedded prototype or video as a link under its caption."""
    caption = markdown_text(embed.caption)
    url = embed.source_url.strip()
    target = safe_link_target(url)
    if target is None:
        link = escape_line_starts(escape_markdown(" ".join(url.split())))
    else:
        link = f"[{escape_markdown(url)}]({target})"
    return "\n\n".join(part for part in (caption, link) if part)


def has_captions(plan: GalleryPlan) -> bool:
    """Report whether the page renders any author-written prose."""
    markup = [block.markup for block in plan.texts]
    markup.extend(asset.caption for asset in plan.images)
    markup.extend(embed.caption for embed in plan.embeds)
    return any(markdown_text(text) for text in markup)


def render_captions(plan: GalleryPlan, saved_names: Mapping[str, str]) -> str:
    """Render the page as Markdown in page order, linking every image under its saved name."""
    entries: list[tuple[int, str]] = [
        (asset.position, image_markdown(asset, saved_names)) for asset in plan.images
    ]
    entries.extend((embed.position, embed_markdown(embed)) for embed in plan.embeds)
    entries.extend((block.position, markdown_text(block.markup)) for block in plan.texts)
    body = "\n\n".join(text for _position, text in sorted(entries, key=itemgetter(0)) if text)
    title = escape_markdown(" ".join(plan.project.name.split())) or str(plan.project.id)
    if not body:
        return f"# {title}\n"
    return f"# {title}\n\n{body}\n"
