"""Tests for reading gallery pages and the project data they carry."""

from __future__ import annotations

import pytest

from behance_dl.errors import GalleryError
from behance_dl.gallery import (
    embed_assets,
    fetch_project,
    image_sources,
    is_behance_host,
    is_behance_url,
    parse_gallery_id,
)
from behance_dl.models import GalleryProject
from conftest import FakeClient, image_module, store_state_page, variant


@pytest.mark.parametrize(
    ("gallery", "expected"),
    [
        ("123", 123),
        ("https://www.behance.net/gallery/123456789/Sample-Gallery", 123456789),
        ("https://www.behance.net/gallery/123456789", 123456789),
        ("https://behance.net/gallery/7/Slug?l=22", 7),
        ("https://mir-s3-cdn-cf.behance.net/gallery/8/slug", 8),
        ("  https://www.behance.net/gallery/9/slug  ", 9),
    ],
)
def test_parse_gallery_id_accepts_behance_input(gallery: str, expected: int) -> None:
    assert parse_gallery_id(gallery) == expected


@pytest.mark.parametrize(
    "gallery",
    [
        "https://example.com/gallery/5/slug",
        "https://notbehance.net/gallery/5/slug",
        "https://www.behance.net/search/projects?search=x",
        "not a url",
        "",
    ],
)
def test_parse_gallery_id_rejects_foreign_input(gallery: str) -> None:
    with pytest.raises(GalleryError):
        parse_gallery_id(gallery)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://mir-s3-cdn-cf.behance.net/project_modules/1400/a.png", True),
        ("https://www.behance.net/gallery/1/x", True),
        ("http://mir-s3-cdn-cf.behance.net/project_modules/1400/a.png", False),
        ("file:///C:/Windows/win.ini", False),
        ("https://evil.example.com/a.png", False),
        ("https://notbehance.net/a.png", False),
        ("https://cdn.behance.net.evil.com/a.png", False),
        ("", False),
    ],
)
def test_is_behance_url(url: str, expected: bool) -> None:
    assert is_behance_url(url) is expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [("behance.net", True), ("cdn.behance.net", True), ("notbehance.net", False), ("", False)],
)
def test_is_behance_host(host: str, expected: bool) -> None:
    assert is_behance_host(host) is expected


def test_fetch_project_reads_the_inlined_payload() -> None:
    payload = {"id": 55, "name": "Name", "slug": "Slug", "modules": []}
    client = FakeClient(pages={55: store_state_page(payload)})

    project = fetch_project(client, 55)

    assert project.id == 55
    assert project.name == "Name"
    assert project.slug == "Slug"
    assert project.modules == ()
    assert project.payload == payload


def test_fetch_project_requests_a_slugged_url() -> None:
    client = FakeClient(pages={55: store_state_page({"id": 55, "modules": []})})

    fetch_project(client, 55)

    assert client.requested == ["https://www.behance.net/gallery/55/gallery"]


def test_fetch_project_prefers_modules_over_all_modules() -> None:
    module = image_module(1, [variant("source", 100)])
    payload = {"id": 1, "modules": [module], "allModules": [{"__typename": "OtherModule"}]}
    client = FakeClient(pages={1: store_state_page(payload)})

    project = fetch_project(client, 1)

    assert project.modules == (module,)


@pytest.mark.parametrize(
    "page",
    [
        "<html><body>no payload here</body></html>",
        store_state_page({}),
        store_state_page([]),
        '<script type="application/json" id="beconfig-store_state">{not json</script>',
        store_state_page({"modules": 5}),
        store_state_page({"modules": [1, 2]}),
    ],
)
def test_fetch_project_rejects_unusable_pages(page: str) -> None:
    client = FakeClient(pages={1: page})

    with pytest.raises(GalleryError):
        fetch_project(client, 1)


def test_image_sources_expands_media_collections() -> None:
    project = GalleryProject(
        id=1,
        name="",
        slug="",
        modules=(
            image_module(1, [variant("source", 10)]),
            {"__typename": "TextModule", "id": 2},
            {
                "__typename": "MediaCollectionModule",
                "id": 3,
                "components": [
                    {"id": 31, "imageSizes": {"allAvailable": [variant("source", 10)]}},
                    {"id": 32, "imageSizes": {"allAvailable": [variant("source", 10)]}},
                ],
            },
        ),
        payload={},
    )

    assert [prefix for prefix, _ in image_sources(project)] == ["001", "003_01", "003_02"]


def test_embed_assets_record_links_instead_of_files() -> None:
    project = GalleryProject(
        id=1,
        name="",
        slug="",
        modules=(
            {
                "__typename": "EmbedModule",
                "id": 11,
                "caption": "prototype",
                "fluidEmbed": '<iframe src="https://embed.figma.com/a?x=1&amp;y=2"></iframe>',
                "originalWidth": 800,
                "originalHeight": 450,
            },
            {
                "__typename": "VideoModule",
                "id": 12,
                "embed": '<iframe src="https://player.example.com/v/1"></iframe>',
                "width": 600,
                "height": 400,
            },
            {"__typename": "EmbedModule", "id": 13, "fluidEmbed": "<div>no iframe</div>"},
            {"__typename": "TextModule", "id": 14},
        ),
        payload={},
    )

    embeds = embed_assets(project)

    assert [(embed.position, embed.module_id) for embed in embeds] == [(1, 11), (2, 12), (3, 13)]
    assert embeds[0].source_url == "https://embed.figma.com/a?x=1&y=2"
    assert (embeds[0].width, embeds[0].height) == (800, 450)
    assert embeds[1].source_url == "https://player.example.com/v/1"
    assert embeds[2].source_url == ""
