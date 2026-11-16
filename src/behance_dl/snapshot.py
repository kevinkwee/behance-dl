"""Rendering a project page as one offline HTML document."""

from __future__ import annotations

import html
import re
import urllib.parse
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from string import Template

from .gallery import BEHANCE_ORIGIN
from .links import safe_link_target
from .models import EmbedAsset, GalleryPlan, GalleryProject, ImageAsset, Slide, TextBlock

_ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "div",
        "em",
        "i",
        "li",
        "ol",
        "p",
        "s",
        "span",
        "strong",
        "u",
        "ul",
    }
)
_VOID_TAGS = frozenset({"br"})
_DROPPED_CONTENT_TAGS = frozenset({"script", "style"})
_ALLOWED_CLASSES = frozenset({"bold", "italic", "underline"})

_COLOR = r"(?:#[0-9A-Fa-f]{3,8}|rgba?\([\d\s.,%]+\)|[A-Za-z]{3,20})"
_STYLE_RULES = {
    "text-align": re.compile(r"(?:left|center|right|justify)"),
    "color": re.compile(_COLOR),
    "background-color": re.compile(_COLOR),
    "font-size": re.compile(r"\d{1,3}(?:\.\d+)?(?:px|em|rem|%|pt|vw|vh)"),
    "font-family": re.compile(r"[A-Za-z0-9 ,'\"_-]{1,100}"),
    "font-weight": re.compile(r"(?:normal|bold|bolder|lighter|[1-9]00)"),
    "font-style": re.compile(r"(?:normal|italic|oblique)"),
    "text-decoration": re.compile(
        r"(?:none|underline|line-through|overline)(?: (?:underline|line-through|overline))*"
    ),
}

_CANVAS_SELECTOR = "#primary-project-content"
_MODULE_SELECTOR = "#primary-project-content .module"
_TEXT_SELECTOR = ".main-text"
_CAPTION_SELECTOR = ".caption"
_PIXEL_VALUE = re.compile(r"(\d{1,4})px")
_COLOR_VALUE = re.compile(_COLOR)
_TAG = re.compile(r"<[^>]*>")
_MAX_STYLESHEET_LENGTH = 20_000
_MAX_OPEN_DEPTH = 32
_MAX_GAP = 200
_MIN_FONT_SIZE = 8
_MAX_FONT_SIZE = 72
_MIN_ROW_WEIGHT = 0.01

_BLOCK_OPENERS = frozenset({"blockquote", "div", "li", "ol", "p", "ul"})
_LIST_CONTAINERS = frozenset({"blockquote", "ol", "ul"})
_NO_STOP: frozenset[str] = frozenset()

_STYLE = Template(
    """
* { box-sizing: border-box; }
body {
  margin: 0;
  background: $background;
  color: #191919;
  font:
    16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
a { color: #0057ff; }
img { max-width: 100%; }
.page { max-width: 1400px; margin: 0 auto; padding: 40px 0 56px; }
header, footer { padding: 0 16px; }
header { margin: 0 0 40px; }
h1 { margin: 0 0 8px; font-size: 32px; line-height: 1.2; }
.creator { margin: 0; color: #666; }
.creator a { color: inherit; text-decoration: none; }
.description { margin: 16px 0 0; max-width: 800px; white-space: pre-line; }
.slide { margin: 0 0 ${gap}px; }
.slide > img { display: block; margin: 0 auto; width: 100%; height: auto; }
.row { display: flex; align-items: flex-start; gap: 4px; padding: 0 7%; }
.row img { display: block; flex-basis: 0; min-width: 0; height: auto; }
.caption {
  margin: 8px 0 0;
  padding: 0 16px;
  font-size: ${caption_size}px;
  color: $caption_color;
}
.text {
  max-width: 800px;
  margin: ${gap}px auto;
  padding: 0 16px;
  font-size: ${text_size}px;
  line-height: 1.4;
  color: $text_color;
  overflow-wrap: break-word;
}
.embed { max-width: 800px; margin: ${gap}px auto; padding: 0 16px; overflow-wrap: break-word; }
.embed .caption { padding: 0; margin: 0 0 8px; }
footer {
  margin-top: 48px;
  padding-top: 16px;
  border-top: 1px solid #e6e6e6;
  font-size: 14px;
  color: #666;
}
footer a { color: inherit; }
.bold { font-weight: 700; }
.italic { font-style: italic; }
.underline { text-decoration: underline; }
""".strip()
)


@dataclass(frozen=True)
class _CanvasStyle:
    """The canvas values the page sets for itself, with the defaults this document uses."""

    background: str = "#fff"
    gap: int = 32
    text_color: str = "#191919"
    text_size: int = 20
    caption_color: str = "#191919"
    caption_size: int = 14


class _MarkupSanitiser(HTMLParser):
    """Reduce payload rich text to the tags and attributes this document allows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._open: list[str] = []
        self._skipped: Counter[str] = Counter()
        self._dropped = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROPPED_CONTENT_TAGS:
            self._dropped += 1
            return
        if self._dropped or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        self._close_implicit(tag)
        if len(self._open) >= _MAX_OPEN_DEPTH:
            self._skipped[tag] += 1
            return
        self._parts.append(f"<{tag}{self._attributes(tag, attrs)}>")
        self._open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._dropped or tag not in _ALLOWED_TAGS:
            return
        attributes = self._attributes(tag, attrs)
        if tag in _VOID_TAGS:
            self._parts.append(f"<{tag}{attributes}>")
        else:
            self._close_implicit(tag)
            self._parts.append(f"<{tag}{attributes}></{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROPPED_CONTENT_TAGS:
            self._dropped = max(0, self._dropped - 1)
            return
        if self._dropped or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        if self._skipped[tag] > 0:
            self._skipped[tag] -= 1
            return
        if tag not in self._open:
            return
        while self._open:
            opened = self._open.pop()
            self._skipped.clear()
            self._parts.append(f"</{opened}>")
            if opened == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self._dropped:
            self._parts.append(html.escape(data, quote=False))

    def render(self) -> str:
        """Return the markup gathered so far, closed so it cannot spill into the page."""
        while self._open:
            self._parts.append(f"</{self._open.pop()}>")
        return "".join(self._parts)

    def _close_implicit(self, tag: str) -> None:
        """Close what a browser closes before this start tag, matching the browser's tree."""
        if tag in _BLOCK_OPENERS:
            self._close_open("p", _NO_STOP)
        if tag == "li":
            self._close_open("li", _LIST_CONTAINERS)
        if tag == "a":
            self._close_open("a", _NO_STOP)

    def _close_open(self, target: str, stop: frozenset[str]) -> None:
        """Close the nearest open target and the elements above it, unless a stop sits between."""
        if target not in self._open:
            return
        index = len(self._open) - 1 - self._open[::-1].index(target)
        if any(item in stop for item in self._open[index + 1 :]):
            return
        while len(self._open) > index:
            self._parts.append(f"</{self._open.pop()}>")
            self._skipped.clear()

    def _attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        values = dict(attrs)
        kept = ""
        if tag == "a":
            href = values.get("href")
            target = safe_link_target(href) if isinstance(href, str) else None
            if target is not None:
                kept += f' href="{html.escape(target, quote=True)}" rel="noopener noreferrer"'
        classes = [name for name in (values.get("class") or "").split() if name in _ALLOWED_CLASSES]
        if classes:
            kept += f' class="{" ".join(classes)}"'
        style = values.get("style")
        if isinstance(style, str):
            declarations = _style_declarations(style)
            if declarations:
                kept += f' style="{html.escape(declarations, quote=True)}"'
        return kept


def _style_declarations(style: str) -> str:
    """Keep only the declarations this document is willing to apply."""
    kept: list[str] = []
    for declaration in style.split(";"):
        name, separator, value = declaration.partition(":")
        if not separator:
            continue
        property_name = name.strip().lower()
        rule = _STYLE_RULES.get(property_name)
        candidate = " ".join(value.split())
        if rule is not None and rule.fullmatch(candidate):
            kept.append(f"{property_name}: {candidate}")
    return "; ".join(kept)


def _sanitise_markup(markup: str) -> str:
    """Return payload rich text reduced to what the snapshot may carry."""
    sanitiser = _MarkupSanitiser()
    try:
        sanitiser.feed(markup)
        sanitiser.close()
        return sanitiser.render()
    except (AssertionError, ValueError):
        # The parser can refuse markup or a character reference, and the words still matter.
        return html.escape(markup)


def snapshot_name(project: GalleryProject) -> str:
    """Return the snapshot's file name, whose stem is the project's gallery folder name."""
    return f"{project.folder_name}.html"


def render_snapshot(plan: GalleryPlan, saved_names: Mapping[str, str]) -> str:
    """Render the page as one document, in page order, linking every image by its saved name."""
    rendered: list[str] = []
    for entry in plan.entries:
        if isinstance(entry, Slide):
            rendered.append(_slide_html(entry, saved_names))
        elif isinstance(entry, EmbedAsset):
            rendered.append(_embed_html(entry))
        else:
            rendered.append(_text_html(entry))
    canvas = _canvas_style(plan.project.payload)
    return _document(plan.project, "".join(rendered), canvas)


def _slide_html(slide: Slide, saved_names: Mapping[str, str]) -> str:
    captions = [_sanitise_markup(asset.caption) for asset in slide.images]
    if slide.is_collection or len(slide.images) > 1:
        images = "".join(
            _row_image(asset, saved_names, caption)
            for asset, caption in zip(slide.images, captions, strict=True)
        )
        body = f'<div class="row">{images}</div>'
    else:
        body = _slide_image(slide, saved_names, captions[0])
    captions.append(_sanitise_markup(slide.collection_caption))
    prose = "".join(_caption_html(caption) for caption in captions)
    return f'<div class="slide">{body}{prose}</div>\n'


def _caption_html(sanitised: str) -> str:
    """Render a caption when the author wrote words there, not an empty block."""
    if not _visible_text(sanitised):
        return ""
    return f'<div class="caption">{sanitised}</div>'


def _visible_text(markup: str) -> str:
    """Return the words of rendered markup, without tags or surrounding space."""
    return _TAG.sub("", markup).strip()


def _slide_image(slide: Slide, saved_names: Mapping[str, str], caption: str) -> str:
    asset = slide.images[0]
    capped = not slide.is_full_bleed and asset.display_width > 0
    style = f' style="max-width: {asset.display_width}px"' if capped else ""
    return _image_tag(asset, saved_names, style, caption)


def _row_image(asset: ImageAsset, saved_names: Mapping[str, str], caption: str) -> str:
    aspect = 1.0
    if asset.display_width > 0 and asset.display_height > 0:
        aspect = max(asset.display_width / asset.display_height, _MIN_ROW_WEIGHT)
    return _image_tag(asset, saved_names, f' style="flex-grow: {aspect:.4f}"', caption)


def _image_tag(
    asset: ImageAsset, saved_names: Mapping[str, str], attributes: str, caption: str
) -> str:
    name = html.escape(saved_names.get(asset.file_name, asset.file_name), quote=True)
    size = ""
    if asset.display_width > 0 and asset.display_height > 0:
        size = f' width="{asset.display_width}" height="{asset.display_height}"'
    alt = _alt_text(caption, asset.file_name)
    return f'<img src="{name}" alt="{alt}" loading="lazy"{size}{attributes}>'


def _alt_text(sanitised: str, fallback: str) -> str:
    """Return what a screen reader should hear for an image."""
    words = " ".join(_visible_text(sanitised).split())
    return html.escape(html.unescape(words) or fallback, quote=True)


def _embed_html(embed: EmbedAsset) -> str:
    prose = _caption_html(_sanitise_markup(embed.caption))
    url = embed.source_url.strip()
    target = safe_link_target(url)
    if target is None:
        link = html.escape(" ".join(url.split()))
    else:
        link = (
            f'<a href="{html.escape(target, quote=True)}" rel="noopener noreferrer">'
            f"{html.escape(url)}</a>"
        )
    return f'<div class="embed">{prose}{link}</div>\n' if prose or url else ""


def _text_html(block: TextBlock) -> str:
    return f'<div class="text">{_sanitise_markup(block.markup)}</div>\n'


def _canvas_style(payload: Mapping[str, object]) -> _CanvasStyle:
    """Read the canvas values the page sets for itself, keeping the defaults otherwise."""
    stylesheet = payload.get("stylesInline")
    if not isinstance(stylesheet, str):
        return _CanvasStyle()
    defaults = _CanvasStyle()
    background = _first(_values(stylesheet, _CANVAS_SELECTOR, "background-color"), _color_value)
    gap = _first(_values(stylesheet, _MODULE_SELECTOR, "padding-bottom"), _pixel_value)
    text_color = _first(_values(stylesheet, _TEXT_SELECTOR, "color"), _color_value)
    text_size = _first(_values(stylesheet, _TEXT_SELECTOR, "font-size"), _font_size)
    caption_color = _first(_values(stylesheet, _CAPTION_SELECTOR, "color"), _color_value)
    caption_size = _first(_values(stylesheet, _CAPTION_SELECTOR, "font-size"), _font_size)
    return _CanvasStyle(
        background=background or defaults.background,
        gap=gap if gap is not None and gap <= _MAX_GAP else defaults.gap,
        text_color=text_color or defaults.text_color,
        text_size=text_size or defaults.text_size,
        caption_color=caption_color or defaults.caption_color,
        caption_size=caption_size or defaults.caption_size,
    )


def _values(stylesheet: str, selector: str, property_name: str) -> list[str]:
    """Return the values a page stylesheet gives one selector, the winning one first."""
    plain: list[str] = []
    important: list[str] = []
    for selectors, body in _rules(stylesheet):
        if not any(_selects(name.strip(), selector) for name in selectors.split(",")):
            continue
        for name, declared in _declarations(body):
            if name.strip().lower() == property_name:
                value, flagged = _split_importance(declared)
                (important if flagged else plain).append(value)
    return important[::-1] + plain[::-1]


def _first[T](values: list[str], validate: Callable[[str], T | None]) -> T | None:
    """Return the first value a validator accepts, so an invalid one does not hide a valid one."""
    for value in values:
        valid = validate(value)
        if valid is not None:
            return valid
    return None


def _rules(stylesheet: str) -> Iterator[tuple[str, str]]:
    """Yield each selector list and its rule body, skipping at-rules and anything nested."""
    text = stylesheet[:_MAX_STYLESHEET_LENGTH]
    position = 0
    while True:
        opening = text.find("{", position)
        if opening < 0:
            return
        semicolon = text.find(";", position, opening)
        if semicolon >= 0:
            position = semicolon + 1
            continue
        selectors = text[position:opening]
        if selectors.lstrip().startswith("@"):
            position = _end_of_block(text, opening)
            continue
        closing = text.find("}", opening + 1)
        if closing < 0:
            return
        yield selectors, text[opening + 1 : closing]
        position = closing + 1


def _end_of_block(text: str, opening: int) -> int:
    """Return the position just past the closing brace of a block that may hold others."""
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def _declarations(body: str) -> Iterator[tuple[str, str]]:
    """Yield each property and its value in a rule body."""
    for declaration in body.split(";"):
        name, separator, value = declaration.partition(":")
        if separator:
            yield name, value


def _split_importance(declared: str) -> tuple[str, bool]:
    """Return a declaration value and whether it carried an importance flag."""
    value = " ".join(declared.split())
    if value.lower().endswith("important"):
        head = value[: -len("important")].rstrip()
        if head.endswith("!"):
            return head[:-1].rstrip(), True
    return value, False


def _selects(candidate: str, selector: str) -> bool:
    """Report whether a page selector is the wanted selector, or ends with it as a descendant."""
    normalised = " ".join(candidate.split())
    if ":" in normalised:
        return False
    return normalised == selector or normalised.endswith(f" {selector}")


def _color_value(value: str) -> str | None:
    return value if _COLOR_VALUE.fullmatch(value) else None


def _pixel_value(value: str) -> int | None:
    if value == "0":
        return 0
    match = _PIXEL_VALUE.fullmatch(value)
    return int(match.group(1)) if match else None


def _font_size(value: str) -> int | None:
    size = _pixel_value(value)
    return size if size is not None and _MIN_FONT_SIZE <= size <= _MAX_FONT_SIZE else None


def _document(project: GalleryProject, body: str, canvas: _CanvasStyle) -> str:
    title = html.escape(" ".join(project.name.split())) or str(project.id)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"<style>\n{_render_style(canvas)}\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="page">\n'
        f"{_header(project, title)}\n"
        f"<main>\n{body}</main>\n"
        f"{_footer(project)}\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


def _render_style(canvas: _CanvasStyle) -> str:
    return _STYLE.substitute(
        background=canvas.background,
        gap=canvas.gap,
        text_color=canvas.text_color,
        text_size=canvas.text_size,
        caption_color=canvas.caption_color,
        caption_size=canvas.caption_size,
    )


def _header(project: GalleryProject, title: str) -> str:
    lines = [f"<h1>{title}</h1>"]
    creator = project.payload.get("creator")
    if isinstance(creator, dict):
        lines.append(_creator_line(creator))
    description = project.payload.get("description")
    if isinstance(description, str) and description.strip():
        lines.append(f'<p class="description">{html.escape(description.strip())}</p>')
    return "<header>\n" + "\n".join(line for line in lines if line) + "\n</header>"


def _creator_line(creator: dict[str, object]) -> str:
    name = creator.get("displayName")
    if not isinstance(name, str) or not name.strip():
        return ""
    label = html.escape(" ".join(name.split()))
    href = creator.get("url")
    target = safe_link_target(href) if isinstance(href, str) else None
    if target is None:
        return f'<p class="creator">by {label}</p>'
    return (
        f'<p class="creator">by <a href="{html.escape(target, quote=True)}" '
        f'rel="noopener noreferrer">{label}</a></p>'
    )


def _footer(project: GalleryProject) -> str:
    slug = urllib.parse.quote(project.slug, safe="", errors="replace")
    address = f"{BEHANCE_ORIGIN}/gallery/{project.id}"
    if slug:
        address = f"{address}/{slug}"
    return (
        f'<footer><a href="{html.escape(address, quote=True)}">'
        "View the original project on Behance</a></footer>"
    )
