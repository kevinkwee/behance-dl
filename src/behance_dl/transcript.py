"""Rendering a project page as a Markdown transcript."""

from __future__ import annotations

import re
from collections.abc import Mapping
from html.parser import HTMLParser

from .links import safe_link_target
from .models import EmbedAsset, GalleryPlan, GalleryProject, ImageAsset, Slide

_BLOCK_TAGS = frozenset({"div", "p", "li"})
_MARKDOWN_SPECIALS = frozenset("\\`*_{}[]<>&#!|~")
_LINE_START_BULLET = re.compile(r"^([ \t]*)([-+])(?=\s|$)", re.MULTILINE)
_LINE_START_NUMBER = re.compile(r"^([ \t]*)(\d{1,9})([.)])(?=\s|$)", re.MULTILINE)
_LINE_START_SETEXT = re.compile(r"^([=-]+)[ \t]*$", re.MULTILINE)
_BLANK_RUNS = re.compile(r"\n{3,}")


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
        """Return the Markdown gathered from the fed markup, with runs of blank lines collapsed."""
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
            # Keep only the single space a link spreads across a block, so the label cannot grow.
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
        # The parser can refuse markup or a character reference, and the words still matter.
        return escape_line_starts(escape_markdown(markup))


def image_link(asset: ImageAsset, saved_names: Mapping[str, str]) -> str:
    """Render one image as a reference to the name it was saved under."""
    name = asset.file_name
    return f"![{name}]({saved_names.get(name, name)})"


def slide_markdown(slide: Slide, saved_names: Mapping[str, str]) -> str:
    """Render a module's images on one line, followed by its captions."""
    links = " ".join(image_link(asset, saved_names) for asset in slide.images)
    captions = [markdown_text(asset.caption) for asset in slide.images]
    captions.append(markdown_text(slide.collection_caption))
    return "\n\n".join(part for part in (links, *captions) if part)


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


def transcript_name(project: GalleryProject) -> str:
    """Return the transcript's file name, whose stem is the project's gallery folder name."""
    return f"{project.folder_name}.md"


def render_transcript(plan: GalleryPlan, saved_names: Mapping[str, str]) -> str:
    """Render the page as Markdown in page order, linking every image by its saved name."""
    rendered: list[str] = []
    for entry in plan.entries:
        if isinstance(entry, Slide):
            rendered.append(slide_markdown(entry, saved_names))
        elif isinstance(entry, EmbedAsset):
            rendered.append(embed_markdown(entry))
        else:
            rendered.append(markdown_text(entry.markup))
    body = "\n\n".join(text for text in rendered if text)
    title = escape_markdown(" ".join(plan.project.name.split())) or str(plan.project.id)
    if not body:
        return f"# {title}\n"
    return f"# {title}\n\n{body}\n"
