"""Tests for rendering a page as a Markdown transcript."""

from __future__ import annotations

from pathlib import Path

import pytest

from behance_dl.models import (
    EmbedAsset,
    GalleryPlan,
    GalleryProject,
    ImageAsset,
    Slide,
    TextBlock,
)
from behance_dl.transcript import (
    MarkdownWriter,
    markdown_text,
    render_transcript,
    transcript_name,
)

IMAGE_URL = "https://mir-s3-cdn-cf.behance.net/project_modules/source/abc.png"


def make_plan(
    *,
    slides: tuple[Slide, ...] = (),
    embeds: tuple[EmbedAsset, ...] = (),
    texts: tuple[TextBlock, ...] = (),
    name: str = "Example",
    slug: str = "Example",
) -> GalleryPlan:
    project = GalleryProject(id=42, name=name, slug=slug, modules=(), payload={"id": 42})
    return GalleryPlan(
        project=project,
        slides=slides,
        embeds=embeds,
        destination=Path("unused"),
        expected_images=sum(len(item.images) for item in slides),
        texts=texts,
    )


def slide(
    position: int,
    *images: ImageAsset,
    collection: bool = False,
    caption: str = "",
) -> Slide:
    return Slide(
        position=position,
        images=images,
        is_collection=collection,
        collection_caption=caption,
    )


def embed(position: int, caption: str, source_url: str) -> EmbedAsset:
    return EmbedAsset(
        position=position,
        module_id=position,
        caption=caption,
        source_url=source_url,
        width=800,
        height=450,
    )


def test_markdown_text_keeps_each_block_on_its_own_line() -> None:
    markup = "<div>One</div><div>Two</div>"

    assert markdown_text(markup) == "One\nTwo"


def test_markdown_text_keeps_an_empty_block_as_a_blank_line() -> None:
    markup = "<div>One</div><div><br></div><div>Two</div>"

    assert markdown_text(markup) == "One\n\nTwo"


def test_markdown_text_treats_paragraphs_and_list_items_as_lines() -> None:
    assert markdown_text("<p>One</p><li>Two</li>") == "One\nTwo"


def test_markdown_text_squashes_a_run_of_blank_lines() -> None:
    markup = "<div>One</div><div><br></div><div><br></div><div><br></div><div>Two</div>"

    assert markdown_text(markup) == "One\n\nTwo"


def test_markdown_text_strips_indentation_that_would_make_a_code_block() -> None:
    markup = "<div>One</div><div><br></div><div>    Two</div>"

    assert markdown_text(markup) == "One\n\nTwo"


def test_markdown_text_keeps_an_inline_span_inside_its_line() -> None:
    markup = '<div>Brand <span class="bold">MARROW</span></div>'

    assert markdown_text(markup) == "Brand MARROW"


def test_markdown_text_decodes_entities() -> None:
    assert markdown_text("<div>Tom &amp; Jerry</div>") == r"Tom \& Jerry"


def test_markdown_text_keeps_a_literal_entity_as_text() -> None:
    assert markdown_text("<div>&amp;lt;b&amp;gt;</div>") == r"\&lt;b\&gt;"


def test_markdown_text_renders_a_self_closing_break() -> None:
    assert markdown_text("<div>One<br/>Two</div>") == "One\nTwo"


def test_markdown_text_renders_empty_markup_as_nothing() -> None:
    assert markdown_text("") == ""


def test_markdown_text_escapes_markdown_syntax() -> None:
    markup = "<div>[click](https://evil.example.com)</div>"

    assert markdown_text(markup) == r"\[click\](https://evil.example.com)"


def test_markdown_text_escapes_a_tag_that_was_written_as_entities() -> None:
    markup = "<div>&lt;img src=x onerror=alert(1)&gt;</div>"

    assert markdown_text(markup) == r"\<img src=x onerror=alert(1)\>"


def test_markdown_text_escapes_a_line_that_looks_like_a_list_item() -> None:
    assert markdown_text("<div>- not a bullet</div>") == r"\- not a bullet"


def test_markdown_text_escapes_a_line_that_looks_like_an_ordered_item() -> None:
    assert markdown_text("<div>1. step</div>") == r"1\. step"


@pytest.mark.parametrize("marker", ["===", "---", "====="])
def test_markdown_text_escapes_a_line_that_looks_like_a_setext_heading(marker: str) -> None:
    assert markdown_text(f"<div>Title</div><div>{marker}</div>") == f"Title\n\\{marker}"


def test_markdown_text_renders_an_https_link() -> None:
    markup = '<a href="https://wa.me/1">WhatsApp</a>'

    assert markdown_text(markup) == "[WhatsApp](https://wa.me/1)"


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "javascript://x.test/%0Aalert(1)",
        "file://host/share/x",
        "https:///x",
        "ht\ttps://evil.test/../../x",
        "\x01https://x.test/",
        "http://[",
        "https://[notip]/",
        "https://x.test\uff03y/z",
    ],
)
def test_markdown_text_keeps_an_unsafe_link_target_as_plain_text(href: str) -> None:
    assert markdown_text(f'<a href="{href}">Click me</a>') == "Click me"


def test_markdown_text_keeps_an_anchor_url_that_cannot_be_encoded() -> None:
    markup = '<a href="https://x.test/\ud800">Click me</a>'

    assert markdown_text(markup) == "Click me"


def test_markdown_text_keeps_the_words_after_a_reference_too_long_to_decode() -> None:
    digits = "9" * 5000

    rendered = markdown_text(f"<div>&#{digits};after</div>")

    assert "after" in rendered


def test_markdown_text_encodes_a_destination_that_would_close_the_link() -> None:
    markup = '<a href="https://x.test/)[x](javascript:alert(1)">c</a>'

    assert markdown_text(markup) == "[c](https://x.test/%29%5Bx%5D%28javascript:alert%281%29)"


def test_markdown_text_escapes_a_link_label() -> None:
    markup = '<a href="https://x.test/">[a]</a>'

    assert markdown_text(markup) == r"[\[a\]](https://x.test/)"


def test_markdown_text_drops_an_empty_link_label() -> None:
    assert markdown_text('<a href="https://x.test/"></a>after') == "after"


def test_markdown_text_keeps_a_whitespace_only_link_label_as_a_space() -> None:
    markup = '<div>word<a href="https://x.test/"> </a>word</div>'

    assert markdown_text(markup) == "word word"


def test_markdown_text_does_not_break_a_line_for_a_whitespace_only_link() -> None:
    markup = '<div>a</div><a href="https://x.test/"> </a><div>b</div>'

    assert markdown_text(markup) == "a\nb"


def test_markdown_text_keeps_a_line_break_inside_a_link_on_one_line() -> None:
    markup = '<a href="https://a.test/">line1<br>line2</a>'

    assert markdown_text(markup) == "[line1 line2](https://a.test/)"


def test_markdown_text_keeps_the_text_after_an_unclosed_link() -> None:
    markup = '<div>See <a href="https://x.test/">this link and the rest</div><div>Second para</div>'

    assert markdown_text(markup) == ("See [this link and the rest](https://x.test/)\nSecond para")


def test_markdown_text_keeps_a_space_around_a_link_label() -> None:
    markup = '<div>word<a href="https://x.test/"> link</a></div>'

    assert markdown_text(markup) == "word [link](https://x.test/)"


def test_markdown_text_keeps_a_link_that_wraps_a_block() -> None:
    markup = '<a href="https://x.test/"><div>text</div></a>'

    assert markdown_text(markup) == "[text](https://x.test/)"


def test_markdown_text_keeps_a_link_open_across_many_empty_blocks() -> None:
    markup = '<a href="https://x.test/">' + "<div> </div>" * 20000 + "end</a>"

    assert markdown_text(markup) == "[end](https://x.test/)"


def test_markdown_text_keeps_a_link_left_open_at_the_end() -> None:
    markup = 'Caption with <a href="https://x.test/">trailing link text'

    assert markdown_text(markup) == "Caption with [trailing link text](https://x.test/)"


def test_markdown_text_keeps_the_text_of_a_nested_link() -> None:
    markup = '<a href="https://a.test/">one <a href="https://b.test/">two</a></a>'

    assert markdown_text(markup) == "[one](https://a.test/) [two](https://b.test/)"


def test_markdown_text_keeps_the_words_of_an_unknown_marked_section() -> None:
    assert "after" in markdown_text("<![foo[ x ]]>after")


def test_markdown_text_falls_back_to_plain_text_when_the_parser_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(self: MarkdownWriter, markup: str) -> None:
        raise AssertionError("unknown status keyword 'foo' in marked section")

    monkeypatch.setattr(MarkdownWriter, "feed", refuse)

    assert markdown_text("<div>words</div>") == r"\<div\>words\</div\>"


def test_markdown_text_escapes_a_line_start_in_the_parser_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(self: MarkdownWriter, markup: str) -> None:
        raise AssertionError("unknown status keyword 'foo' in marked section")

    monkeypatch.setattr(MarkdownWriter, "feed", refuse)

    assert markdown_text("<div>one</div>\n- two") == "\\<div\\>one\\</div\\>\n\\- two"


def test_render_transcript_places_text_between_its_neighbouring_images() -> None:
    plan = make_plan(
        slides=(
            slide(1, ImageAsset(file_prefix="001", url=IMAGE_URL, width=100)),
            slide(3, ImageAsset(file_prefix="003", url=IMAGE_URL, width=100)),
        ),
        texts=(TextBlock(position=2, markup="<div>Between</div>"),),
    )

    document = render_transcript(plan, {})

    assert document == (
        "# Example\n\n![001_abc.png](001_abc.png)\n\nBetween\n\n![003_abc.png](003_abc.png)\n"
    )


def test_render_transcript_keeps_collection_components_in_page_order() -> None:
    prefixes = ["005_09", "005_99", "005_100", "005_101"]
    assets = tuple(ImageAsset(file_prefix=prefix, url=IMAGE_URL, width=100) for prefix in prefixes)
    plan = make_plan(
        slides=(slide(5, *assets, collection=True),),
        texts=(TextBlock(position=6, markup="After"),),
    )

    document = render_transcript(plan, {})

    positions = [document.index(prefix) for prefix in prefixes]
    assert positions == sorted(positions)


def test_render_transcript_puts_collection_components_on_one_line() -> None:
    plan = make_plan(
        slides=(
            slide(
                1,
                ImageAsset(file_prefix="001_01", url=IMAGE_URL, width=100),
                ImageAsset(file_prefix="001_02", url=IMAGE_URL, width=100),
                collection=True,
            ),
        )
    )

    document = render_transcript(plan, {})

    assert "![001_01_abc.png](001_01_abc.png) ![001_02_abc.png](001_02_abc.png)\n" in document


def test_render_transcript_renders_the_collection_caption_under_the_row() -> None:
    plan = make_plan(
        slides=(
            slide(
                1,
                ImageAsset(file_prefix="001_01", url=IMAGE_URL, width=100),
                collection=True,
                caption="<div>Two boos</div>",
            ),
        )
    )

    assert render_transcript(plan, {}) == (
        "# Example\n\n![001_01_abc.png](001_01_abc.png)\n\nTwo boos\n"
    )


def test_render_transcript_renders_a_component_caption_under_the_row() -> None:
    plan = make_plan(
        slides=(
            slide(
                1,
                ImageAsset(file_prefix="001_01", url=IMAGE_URL, width=100),
                ImageAsset(file_prefix="001_02", url=IMAGE_URL, width=100, caption="Left boo"),
                collection=True,
            ),
        )
    )

    assert render_transcript(plan, {}) == (
        "# Example\n\n![001_01_abc.png](001_01_abc.png) ![001_02_abc.png](001_02_abc.png)"
        "\n\nLeft boo\n"
    )


def test_render_transcript_renders_an_embed_caption_above_its_link() -> None:
    plan = make_plan(embeds=(embed(1, "Prototype", "https://embed.figma.com/x"),))

    assert render_transcript(plan, {}) == (
        "# Example\n\nPrototype\n\n[https://embed.figma.com/x](https://embed.figma.com/x)\n"
    )


def test_render_transcript_labels_an_embed_without_a_caption_by_its_url() -> None:
    plan = make_plan(embeds=(embed(1, "", "https://v.test/1"),))

    assert render_transcript(plan, {}) == "# Example\n\n[https://v.test/1](https://v.test/1)\n"


def test_render_transcript_links_the_name_the_file_was_saved_under() -> None:
    plan = make_plan(
        slides=(slide(1, ImageAsset(file_prefix="001", url=IMAGE_URL, width=100)),),
        texts=(TextBlock(position=2, markup="After"),),
    )

    document = render_transcript(plan, {"001_abc.png": "001_abc.jpg"})

    assert "![001_abc.png](001_abc.jpg)" in document


def test_render_transcript_renders_an_image_caption_under_its_image() -> None:
    plan = make_plan(
        slides=(slide(1, ImageAsset(file_prefix="001", url=IMAGE_URL, width=100, caption="A boo")),)
    )

    assert render_transcript(plan, {}) == "# Example\n\n![001_abc.png](001_abc.png)\n\nA boo\n"


def test_render_transcript_escapes_a_hostile_project_name() -> None:
    plan = make_plan(
        slides=(slide(1, ImageAsset(file_prefix="001", url=IMAGE_URL, width=100)),),
        name="[x](javascript:alert(1))",
    )

    assert render_transcript(plan, {}).startswith("# \\[x\\](javascript:alert(1))\n")


def test_render_transcript_keeps_a_project_name_on_one_line() -> None:
    plan = make_plan(
        slides=(slide(1, ImageAsset(file_prefix="001", url=IMAGE_URL, width=100)),),
        name="One\nTwo",
    )

    assert render_transcript(plan, {}).startswith("# One Two\n")


def test_render_transcript_skips_a_block_that_renders_nothing() -> None:
    plan = make_plan(
        slides=(slide(1, ImageAsset(file_prefix="001", url=IMAGE_URL, width=100)),),
        texts=(TextBlock(position=2, markup="<div><br></div>"),),
    )

    assert render_transcript(plan, {}) == "# Example\n\n![001_abc.png](001_abc.png)\n"


def test_render_transcript_omits_an_embed_without_a_label_or_a_link() -> None:
    plan = make_plan(
        slides=(slide(1, ImageAsset(file_prefix="001", url=IMAGE_URL, width=100)),),
        embeds=(embed(2, "", ""),),
    )

    assert render_transcript(plan, {}) == "# Example\n\n![001_abc.png](001_abc.png)\n"


def test_render_transcript_keeps_an_embed_with_a_foreign_link_as_text() -> None:
    plan = make_plan(
        embeds=(embed(1, "", "javascript:alert(1)"),),
        texts=(TextBlock(position=2, markup="After"),),
    )

    assert render_transcript(plan, {}) == "# Example\n\njavascript:alert(1)\n\nAfter\n"


def test_render_transcript_escapes_a_hostile_embed_link_label() -> None:
    plan = make_plan(embeds=(embed(1, "", "https://x.test/](javascript:alert(1))"),))

    assert render_transcript(plan, {}) == (
        "# Example\n\n"
        "[https://x.test/\\](javascript:alert(1))]"
        "(https://x.test/%5D%28javascript:alert%281%29%29)\n"
    )


def test_render_transcript_escapes_an_embed_url_without_a_scheme() -> None:
    plan = make_plan(embeds=(embed(1, "", "[x](javascript:alert(1))"),))

    assert render_transcript(plan, {}) == "# Example\n\n\\[x\\](javascript:alert(1))\n"


def test_render_transcript_renders_an_embed_with_an_unparseable_url_as_text() -> None:
    plan = make_plan(embeds=(embed(1, "", "https://[x"),))

    assert render_transcript(plan, {}) == "# Example\n\nhttps://\\[x\n"


def test_render_transcript_escapes_a_line_start_in_a_rejected_embed_url() -> None:
    plan = make_plan(embeds=(embed(1, "", "- x"),))

    assert render_transcript(plan, {}) == "# Example\n\n\\- x\n"


def test_render_transcript_renders_a_title_alone_when_nothing_else_shows() -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup="<div><br></div>"),))

    assert render_transcript(plan, {}) == "# Example\n"


def test_transcript_name_mirrors_the_project_folder_name() -> None:
    assert transcript_name(make_plan().project) == "42_Example.md"


def test_transcript_name_falls_back_to_the_id_without_a_slug() -> None:
    assert transcript_name(make_plan(slug="").project) == "42.md"


def test_transcript_name_drops_a_traversal_slug() -> None:
    assert transcript_name(make_plan(slug="../../etc").project) == "42_etc.md"
