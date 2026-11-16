"""Tests for rendering a page as one offline HTML document."""

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
from behance_dl.snapshot import render_snapshot, snapshot_name

IMAGE_URL = "https://mir-s3-cdn-cf.behance.net/project_modules/source/abc.png"


def make_plan(
    *,
    slides: tuple[Slide, ...] = (),
    embeds: tuple[EmbedAsset, ...] = (),
    texts: tuple[TextBlock, ...] = (),
    name: str = "Example",
    slug: str = "Example",
    payload: dict[str, object] | None = None,
) -> GalleryPlan:
    project = GalleryProject(
        id=42,
        name=name,
        slug=slug,
        modules=(),
        payload=payload if payload is not None else {"id": 42},
    )
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
    full_bleed: bool = False,
) -> Slide:
    return Slide(
        position=position,
        images=images,
        is_collection=collection,
        collection_caption=caption,
        is_full_bleed=full_bleed,
    )


def image(
    prefix: str = "001",
    *,
    caption: str = "",
    width: int = 0,
    height: int = 0,
) -> ImageAsset:
    return ImageAsset(
        file_prefix=prefix,
        url=IMAGE_URL,
        width=1000,
        caption=caption,
        display_width=width,
        display_height=height,
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


def text_document(markup: str) -> str:
    return render_snapshot(make_plan(texts=(TextBlock(position=1, markup=markup),)), {})


def style_block(document: str, selector: str) -> str:
    start = document.index(f"\n{selector} {{")
    return document[start : document.index("}", start)]


def test_snapshot_name_mirrors_the_project_folder_name() -> None:
    assert snapshot_name(make_plan().project) == "42_Example.html"


def test_snapshot_name_falls_back_to_the_id_without_a_slug() -> None:
    assert snapshot_name(make_plan(slug="").project) == "42.html"


def test_snapshot_name_drops_a_traversal_slug() -> None:
    assert snapshot_name(make_plan(slug="../../etc").project) == "42_etc.html"


def test_render_snapshot_opens_a_document_titled_after_the_project() -> None:
    document = render_snapshot(make_plan(), {})

    assert document.startswith("<!doctype html>\n")
    assert "<title>Example</title>" in document
    assert "<h1>Example</h1>" in document


def test_render_snapshot_shows_the_creator_and_the_description() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "creator": {
                "displayName": "Example Creator",
                "url": "https://www.behance.net/example-creator",
            },
            "description": "First line\nSecond line",
        }
    )

    document = render_snapshot(plan, {})

    assert (
        '<a href="https://www.behance.net/example-creator" rel="noopener noreferrer">'
        "Example Creator</a>"
    ) in document
    assert '<p class="description">First line\nSecond line</p>' in document


def test_render_snapshot_shows_a_creator_without_an_unsafe_profile_link() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "creator": {"displayName": "Example Creator", "url": "javascript:x"},
        }
    )

    document = render_snapshot(plan, {})

    assert '<p class="creator">by Example Creator</p>' in document


def test_render_snapshot_escapes_a_hostile_project_name() -> None:
    document = render_snapshot(make_plan(name="<script>alert(1)</script>"), {})

    assert "<title>&lt;script&gt;alert(1)&lt;/script&gt;</title>" in document


def test_render_snapshot_links_every_image_by_the_name_it_was_saved_under() -> None:
    plan = make_plan(slides=(slide(1, image("001")),))

    document = render_snapshot(plan, {"001_abc.png": "001_abc.jpg"})

    assert '<img src="001_abc.jpg"' in document


def test_render_snapshot_stamps_the_size_the_page_declares() -> None:
    plan = make_plan(slides=(slide(1, image("001", width=600, height=450)),))

    document = render_snapshot(plan, {})

    assert 'width="600" height="450"' in document


def test_render_snapshot_caps_a_non_full_bleed_image_at_its_display_width() -> None:
    plan = make_plan(slides=(slide(1, image("001", width=389, height=389)),))

    assert 'style="max-width: 389px"' in render_snapshot(plan, {})


def test_render_snapshot_lets_a_full_bleed_image_fill_the_column() -> None:
    plan = make_plan(slides=(slide(1, image("001", width=600, height=450), full_bleed=True),))

    document = render_snapshot(plan, {})

    assert '<img src="001_abc.png"' in document
    assert "max-width: 600px" not in document


def test_render_snapshot_keeps_collection_components_in_one_row() -> None:
    plan = make_plan(
        slides=(
            slide(
                1,
                image("001_01", width=320, height=603),
                image("001_02", width=600, height=300),
                collection=True,
            ),
        )
    )

    document = render_snapshot(plan, {})

    assert '<div class="row">' in document
    assert "flex-grow: 0.5307" in document
    assert "flex-grow: 2.0000" in document


def test_render_snapshot_renders_the_collection_caption_below_the_row() -> None:
    plan = make_plan(
        slides=(slide(1, image("001_01"), collection=True, caption="<div>Two boos</div>"),)
    )

    document = render_snapshot(plan, {})

    assert document.index('<div class="row">') < document.index(
        '<div class="caption"><div>Two boos</div></div>'
    )


def test_render_snapshot_weights_a_row_image_without_a_width_by_one() -> None:
    plan = make_plan(slides=(slide(1, image("001_01", width=0, height=603), collection=True),))

    document = render_snapshot(plan, {})

    assert '<img src="001_01_abc.png"' in document
    assert "flex-grow: 1.0000" in document


def test_render_snapshot_orders_modules_by_page_position() -> None:
    plan = make_plan(
        slides=(slide(3, image("003")),),
        texts=(TextBlock(position=2, markup="<div>Between</div>"),),
        embeds=(embed(1, "Prototype", "https://embed.figma.com/x"),),
    )

    document = render_snapshot(plan, {})

    assert document.index("Prototype") < document.index("Between") < document.index("003_abc.png")


def test_render_snapshot_renders_a_text_module() -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup="<div>Words</div>"),))

    assert '<div class="text"><div>Words</div></div>' in render_snapshot(plan, {})


def test_render_snapshot_keeps_a_self_closing_break() -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup="<div>One<br/>Two</div>"),))

    assert "<div>One<br>Two</div>" in render_snapshot(plan, {})


def test_render_snapshot_drops_a_style_declaration_without_a_value() -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup='<div style="color">Words</div>'),))

    assert "<div>Words</div>" in render_snapshot(plan, {})


def test_render_snapshot_ignores_a_creator_without_a_name() -> None:
    plan = make_plan(payload={"id": 42, "creator": {"url": "https://www.behance.net/x"}})

    assert 'class="creator"' not in render_snapshot(plan, {})


def test_render_snapshot_omits_the_slug_from_an_empty_project_slug() -> None:
    document = render_snapshot(make_plan(slug=""), {})

    assert '<a href="https://www.behance.net/gallery/42">' in document


def test_render_snapshot_drops_script_content() -> None:
    plan = make_plan(
        texts=(TextBlock(position=1, markup="<div>Before<script>alert(1)</script>After</div>"),)
    )

    document = render_snapshot(plan, {})

    assert "alert(1)" not in document
    assert "<div>BeforeAfter</div>" in document


def test_render_snapshot_drops_an_event_handler_attribute() -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup='<div onclick="alert(1)">Words</div>'),))

    assert "<div>Words</div>" in render_snapshot(plan, {})


def test_render_snapshot_rejects_a_javascript_link() -> None:
    plan = make_plan(
        texts=(TextBlock(position=1, markup='<div><a href="javascript:alert(1)">Words</a></div>'),)
    )

    document = render_snapshot(plan, {})

    assert "<a>Words</a>" in document
    assert "javascript:" not in document


def test_render_snapshot_keeps_an_author_link() -> None:
    plan = make_plan(
        texts=(
            TextBlock(
                position=1,
                markup='<div><a href="https://example.test/store">Store</a></div>',
            ),
        )
    )

    document = render_snapshot(plan, {})

    assert '<a href="https://example.test/store" rel="noopener noreferrer">Store</a>' in document


def test_render_snapshot_unwraps_an_unknown_tag() -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup="<marquee>Words</marquee>"),))

    assert '<div class="text">Words</div>' in render_snapshot(plan, {})


def test_render_snapshot_keeps_the_classes_this_document_styles() -> None:
    plan = make_plan(
        texts=(TextBlock(position=1, markup='<div><span class="bold evil">Words</span></div>'),)
    )

    assert '<span class="bold">Words</span>' in render_snapshot(plan, {})


def test_render_snapshot_keeps_an_allowed_style() -> None:
    plan = make_plan(
        texts=(
            TextBlock(
                position=1,
                markup='<div style="text-align:center;color:#123456">Words</div>',
            ),
        )
    )

    assert '<div style="text-align: center; color: #123456">Words</div>' in render_snapshot(
        plan, {}
    )


@pytest.mark.parametrize(
    "style",
    [
        "background:url(https://tracker.test/p.gif)",
        "position:fixed",
        "font-size:expression(alert(1))",
        "color:rgb(0 0 0 / 50%)",
    ],
)
def test_render_snapshot_drops_a_disallowed_style(style: str) -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup=f'<div style="{style}">Words</div>'),))

    assert "<div>Words</div>" in render_snapshot(plan, {})


def test_render_snapshot_keeps_a_style_next_to_a_dropped_declaration() -> None:
    plan = make_plan(
        texts=(
            TextBlock(
                position=1,
                markup='<div style="color:red;background-image:url(x)">Words</div>',
            ),
        )
    )

    assert '<div style="color: red">Words</div>' in render_snapshot(plan, {})


def test_render_snapshot_drops_an_image_from_payload_caption_markup() -> None:
    plan = make_plan(slides=(slide(1, image("001", caption="<img src=x onerror=alert(1)>")),))

    document = render_snapshot(plan, {})

    assert "onerror" not in document
    assert "<img src=x" not in document


def test_render_snapshot_survives_markup_the_parser_refuses() -> None:
    plan = make_plan(texts=(TextBlock(position=1, markup="<div>&#" + "9" * 5000 + ";after</div>"),))

    document = render_snapshot(plan, {})

    assert "after" in document
    assert "&lt;div&gt;" in document


def test_render_snapshot_drops_a_stray_end_tag() -> None:
    assert '<main>\n<div class="text">Words</div>\n</main>' in text_document("</div></div>Words")


def test_render_snapshot_closes_an_unclosed_link_before_the_next_slide() -> None:
    plan = make_plan(
        texts=(TextBlock(position=1, markup='<a href="https://evil.test/">click'),),
        slides=(slide(2, image("002")),),
    )

    document = render_snapshot(plan, {})

    assert '</a></div>\n<div class="slide">' in document


def test_render_snapshot_closes_an_unclosed_emphasis() -> None:
    assert '<div class="text"><b>bold</b></div>' in text_document("<b>bold")


def test_render_snapshot_closes_a_self_closing_block() -> None:
    assert '<div class="text"><div></div>after</div>' in text_document("<div/>after")


def test_render_snapshot_drops_a_self_closing_tag_it_does_not_keep() -> None:
    assert '<div class="text"><div>after</div></div>' in text_document(
        "<div><plaintext/>after</div>"
    )


def test_render_snapshot_ignores_an_end_tag_for_a_void_element() -> None:
    assert '<div class="text">after</div>' in text_document("</br>after")


def test_render_snapshot_closes_nested_elements_an_end_tag_skips_over() -> None:
    document = text_document('<div><a href="https://x.test/">a<b>b</div>')

    assert (
        '<div><a href="https://x.test/" rel="noopener noreferrer">a<b>b</b></a></div>' in document
    )


def test_render_snapshot_omits_a_caption_that_holds_no_words() -> None:
    plan = make_plan(slides=(slide(1, image("001", caption="<div></div>")),))

    assert 'class="caption"' not in render_snapshot(plan, {})


def test_render_snapshot_closes_a_list_item_before_the_next_item() -> None:
    assert '<div class="text"><li><div></div></li><li>x</li></div>' in text_document(
        "<li><div><li>x"
    )


def test_render_snapshot_keeps_a_nested_list_inside_its_item() -> None:
    assert '<div class="text"><li><ul><li>x</li></ul></li></div>' in text_document(
        "<li><ul><li>x</ul></li>"
    )


def test_render_snapshot_closes_a_paragraph_before_a_block() -> None:
    assert '<div class="text"><p>a</p><div>b</div></div>' in text_document("<p>a<div>b</div>")


def test_render_snapshot_closes_a_link_before_the_next_link() -> None:
    document = text_document('<a href="https://x.test/1">one<a href="https://x.test/2">two')

    assert "one</a><a href=" in document


def test_render_snapshot_names_an_image_after_its_caption_for_a_reader() -> None:
    plan = make_plan(slides=(slide(1, image("001", caption="<div>A boo</div>")),))

    document = render_snapshot(plan, {})

    assert 'alt="A boo"' in document


def test_render_snapshot_names_an_uncaptioned_image_after_its_file() -> None:
    plan = make_plan(slides=(slide(1, image("001")),))

    assert 'alt="001_abc.png"' in render_snapshot(plan, {})


def test_render_snapshot_takes_the_canvas_background_from_the_page_style() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": (
                "#primary-project-content { padding-top: 0px; background-color: #00C4F1; }"
            ),
        }
    )

    assert "background: #00C4F1;" in render_snapshot(plan, {})


def test_render_snapshot_takes_the_module_gap_from_the_page_style() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "#primary-project-content .module { padding-bottom: 0px; }",
        }
    )

    assert ".slide { margin: 0 0 0px; }" in render_snapshot(plan, {})


def test_render_snapshot_takes_text_type_from_the_page_style() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": ".editor-text .main-text { color: #696969; font-size: 18px; }",
        }
    )

    style = style_block(render_snapshot(plan, {}), ".text")

    assert "font-size: 18px;" in style
    assert "color: #696969;" in style


def test_render_snapshot_takes_caption_type_from_the_page_style() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "#project-modules .caption { color: #a4a4a4; font-size: 12px; }",
        }
    )

    style = style_block(render_snapshot(plan, {}), ".caption")

    assert "font-size: 12px;" in style
    assert "color: #a4a4a4;" in style


@pytest.mark.parametrize(
    "declaration",
    [
        "BACKGROUND-COLOR: #123456",
        "background-color: #123456 !important",
        "background-color: #123456 ! important",
        "background-color: #123456 !IMPORTANT",
    ],
)
def test_render_snapshot_reads_a_declaration_spelled_unusually(declaration: str) -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": f"#primary-project-content {{ {declaration}; }}",
        }
    )

    assert "background: #123456;" in render_snapshot(plan, {})


@pytest.mark.parametrize("size", ["9000px", "2px"])
def test_render_snapshot_keeps_a_text_font_size_inside_its_bounds(size: str) -> None:
    plan = make_plan(payload={"id": 42, "stylesInline": f".main-text {{ font-size: {size}; }}"})

    style = style_block(render_snapshot(plan, {}), ".text")

    assert f"font-size: {size};" not in style
    assert "font-size: 20px;" in style


@pytest.mark.parametrize("size", ["9000px", "2px"])
def test_render_snapshot_keeps_a_caption_font_size_inside_its_bounds(size: str) -> None:
    plan = make_plan(payload={"id": 42, "stylesInline": f".caption {{ font-size: {size}; }}"})

    style = style_block(render_snapshot(plan, {}), ".caption")

    assert f"font-size: {size};" not in style
    assert "font-size: 14px;" in style


def test_render_snapshot_ignores_a_rule_inside_a_media_query() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": (
                "@media screen { a { color: red } "
                "#primary-project-content { background-color: #123456 } }"
            ),
        }
    )

    assert "background: #fff;" in render_snapshot(plan, {})


def test_render_snapshot_ignores_a_pseudo_class_rule() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": ".x:hover .caption { color: #123456; }",
        }
    )

    assert "color: #123456;" not in render_snapshot(plan, {})


def test_render_snapshot_reads_a_selector_split_across_lines() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "#primary-project-content\n\t.module { padding-bottom: 0px; }",
        }
    )

    assert ".slide { margin: 0 0 0px; }" in render_snapshot(plan, {})


def test_render_snapshot_reads_a_module_gap_written_without_a_unit() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "#primary-project-content .module { padding-bottom: 0; }",
        }
    )

    assert ".slide { margin: 0 0 0px; }" in render_snapshot(plan, {})


def test_render_snapshot_stops_reading_a_stylesheet_at_its_length_cap() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "x" * 20_000
            + " #primary-project-content { background-color: #123456; }",
        }
    )

    assert "background: #fff;" in render_snapshot(plan, {})


def test_render_snapshot_reads_the_rule_after_a_statement_at_rule() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": (
                "@import url(https://tracker.test/x); "
                "#primary-project-content { background-color: #123456; }"
            ),
        }
    )

    document = render_snapshot(plan, {})

    assert "background: #123456;" in document
    assert "url(" not in document


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("#111111", "#222222", "#222222"),
        ("#111111 !important", "#222222 !important", "#222222"),
        ("#111111 !important", "#222222", "#111111"),
    ],
)
def test_render_snapshot_orders_declarations_the_way_a_browser_does(
    first: str, second: str, expected: str
) -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": (
                f"#primary-project-content {{ background-color: {first}; "
                f"background-color: {second}; }}"
            ),
        }
    )

    assert f"background: {expected};" in render_snapshot(plan, {})


def test_render_snapshot_reads_an_important_value_without_a_closing_semicolon() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "#primary-project-content { background-color: #123456 !important }",
        }
    )

    assert "background: #123456;" in render_snapshot(plan, {})


def test_render_snapshot_caps_the_nesting_it_keeps() -> None:
    document = text_document("<div>" * 5_000 + "deep" + "</div>" * 5_000)

    block = document.split('<div class="text">', 1)[1]

    assert "deep" in block
    assert block.count("<div>") < 100


def test_render_snapshot_drops_the_end_tag_of_a_tag_skipped_at_the_cap() -> None:
    markup = "<b>" + "<span>" * 31 + "<b>a</b>b"
    block = text_document(markup).split('<div class="text">', 1)[1].split("</div>\n", 1)[0]

    assert "ab" + "</span>" * 31 + "</b>" in block


def test_render_snapshot_closes_a_paragraph_at_the_depth_cap() -> None:
    markup = "<b>" * 31 + "<p>one<p>two"

    assert "<p>one</p><p>two</p>" in text_document(markup)


def test_render_snapshot_forgets_skipped_tags_once_their_container_closes() -> None:
    markup = "<div>" * 32 + "<p>deep" + "</div>" * 32 + "<p>two</p>three"

    assert "<p>two</p>three" in text_document(markup)


def test_render_snapshot_forgets_skipped_tags_when_an_implicit_close_pops_them() -> None:
    markup = "<p>" + "<span>" * 31 + "<b>deep" + "<p>two<b>x</b>y"

    assert "<p>two<b>x</b>y</p>" in text_document(markup)


def test_render_snapshot_sanitises_every_text_slot() -> None:
    hostile = '<script>alert(1)</script><div onclick="alert(2)">Words</div>'
    plan = make_plan(
        slides=(slide(1, image("001", caption=hostile), collection=True, caption=hostile),),
        embeds=(embed(2, hostile, "https://embed.figma.com/x"),),
        texts=(TextBlock(position=3, markup=hostile),),
    )

    document = render_snapshot(plan, {})

    assert "alert(1)" not in document
    assert "onclick" not in document
    assert document.count(">Words<") == 4


def test_render_snapshot_keeps_its_defaults_for_an_unclosed_at_rule() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "@media x { #primary-project-content { background-color: #123456; }",
        }
    )

    assert "background: #fff;" in render_snapshot(plan, {})


def test_render_snapshot_ignores_a_value_that_ends_in_important_without_a_bang() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": "#primary-project-content { background-color: #123456 important; }",
        }
    )

    assert "background: #fff;" in render_snapshot(plan, {})


def test_render_snapshot_keeps_an_earlier_value_when_a_later_one_is_invalid() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": (
                "#primary-project-content { background-color: #111111; "
                "background-color: url(https://tracker.test/x) !important; }"
            ),
        }
    )

    assert "background: #111111;" in render_snapshot(plan, {})


def test_render_snapshot_gives_a_very_thin_row_image_a_visible_weight() -> None:
    plan = make_plan(slides=(slide(1, image("001_01", width=1, height=1000), collection=True),))

    assert "flex-grow: 0.0100" in render_snapshot(plan, {})


@pytest.mark.parametrize(
    "styles",
    [
        "#primary-project-content { background-color: expression(alert(1)); }",
        "#primary-project-content { background-color: url(https://tracker.test/p.gif); }",
        "#primary-project-content .module { padding-bottom: 5000px; }",
        "#primary-project-content { background-color: #123456",
    ],
)
def test_render_snapshot_keeps_its_defaults_for_a_hostile_canvas_style(styles: str) -> None:
    document = render_snapshot(make_plan(payload={"id": 42, "stylesInline": styles}), {})

    assert "background: #fff;" in document
    assert ".slide { margin: 0 0 32px; }" in document


def test_render_snapshot_never_copies_a_page_style_rule() -> None:
    plan = make_plan(
        payload={
            "id": 42,
            "stylesInline": (
                "#primary-project-content { @import url(https://tracker.test/x); "
                "background-color: #123456; }"
            ),
        }
    )

    document = render_snapshot(plan, {})

    assert "background: #123456;" in document
    assert "url(" not in document
    assert "@import" not in document


def test_render_snapshot_renders_an_embed_caption_above_its_link() -> None:
    plan = make_plan(embeds=(embed(1, "<div>Prototype</div>", "https://embed.figma.com/x"),))

    document = render_snapshot(plan, {})

    assert document.index('<div class="caption"><div>Prototype</div></div>') < document.index(
        '<a href="https://embed.figma.com/x" rel="noopener noreferrer">'
    )


def test_render_snapshot_keeps_a_foreign_embed_url_as_text() -> None:
    plan = make_plan(embeds=(embed(1, "", "javascript:alert(1)"),))

    document = render_snapshot(plan, {})

    assert '<div class="embed">javascript:alert(1)</div>' in document


def test_render_snapshot_omits_an_embed_without_a_caption_or_a_link() -> None:
    plan = make_plan(embeds=(embed(1, "", ""),))

    assert '<div class="embed">' not in render_snapshot(plan, {})


def test_render_snapshot_survives_a_lone_surrogate_in_the_slug() -> None:
    document = render_snapshot(make_plan(slug="\ud800"), {})

    assert "https://www.behance.net/gallery/42/%3F" in document


def test_render_snapshot_points_at_the_original_project() -> None:
    document = render_snapshot(make_plan(slug="Example Slug"), {})

    assert (
        '<a href="https://www.behance.net/gallery/42/Example%20Slug">'
        "View the original project on Behance</a>"
    ) in document
