"""Tests for picking one CDN variant per image."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from behance_dl.errors import GalleryError
from behance_dl.models import GalleryProject, TextBlock
from behance_dl.selection import (
    bucket,
    bucket_rank,
    candidate_sizes,
    image_asset,
    plan_gallery,
    select_image_url,
)
from conftest import FakeClient, image_module, store_state_page, variant

if TYPE_CHECKING:
    from pathlib import Path


def url_of(bucket_name: str, width: int, name: str = "abc") -> str:
    """Return the URL variant() would build."""
    return str(variant(bucket_name, width, name=name)["url"])


def test_bucket_reads_the_project_modules_segment() -> None:
    url = "https://mir-s3-cdn-cf.behance.net/project_modules/max_1200/abc.png"

    assert bucket(url) == "max_1200"


def test_bucket_is_empty_for_an_unrelated_path() -> None:
    assert bucket("https://mir-s3-cdn-cf.behance.net/other/abc.png") == ""


def test_bucket_rank_prefers_source_then_plain_then_optimised() -> None:
    assert bucket_rank("source") > bucket_rank("1400") > bucket_rank("1400_opt_1")


def test_stills_are_dropped_when_an_animated_variant_exists() -> None:
    module = image_module(
        1,
        [variant("1400", 1400), variant("1400_still", 1400), variant("fs_still", 1900)],
    )

    assert select_image_url(module, 1400) == (1400, url_of("1400", 1400))


def test_stills_are_used_when_nothing_else_exists() -> None:
    module = image_module(1, [variant("max_1200_still", 1200)])

    assert select_image_url(module, None) == (1200, url_of("max_1200_still", 1200))


def test_plain_bucket_beats_optimised_copy_at_the_same_width() -> None:
    module = image_module(1, [variant("1400_opt_1", 1400), variant("1400", 1400)])

    assert select_image_url(module, 1400) == (1400, url_of("1400", 1400))


def test_source_wins_at_the_same_width() -> None:
    module = image_module(1, [variant("fs", 1900), variant("source", 1900)])

    assert select_image_url(module, None) == (1900, url_of("source", 1900))


def test_webp_variants_are_never_selected() -> None:
    module = image_module(
        1,
        [variant("1400", 1400), variant("1400_webp", 1400, kind="WEBP"), variant("fs_webp", 1900)],
    )

    assert select_image_url(module, None) == (1400, url_of("1400", 1400))


def test_variants_outside_behance_are_ignored() -> None:
    module = image_module(
        1,
        [
            {"url": "file:///C:/Windows/win.ini", "width": 9000, "type": "JPG"},
            {"url": "https://evil.example.com/a.png", "width": 8000, "type": "JPG"},
            variant("1400", 1400),
        ],
    )

    assert select_image_url(module, None) == (1400, url_of("1400", 1400))


def test_max_width_picks_the_largest_variant_that_fits() -> None:
    module = image_module(1, [variant("source", 4000), variant("1400", 1400), variant("disp", 600)])

    assert select_image_url(module, 1500) == (1400, url_of("1400", 1400))


def test_max_width_falls_back_to_the_smallest_variant() -> None:
    module = image_module(1, [variant("hd", 1240), variant("disp", 600)])

    assert select_image_url(module, 100) == (600, url_of("disp", 600))


def test_max_width_fallback_prefers_the_plain_bucket_at_the_smallest_width() -> None:
    module = image_module(1, [variant("disp_opt_1", 600), variant("disp", 600)])

    assert select_image_url(module, 100) == (600, url_of("disp", 600))


def test_preview_is_used_when_no_variant_is_listed() -> None:
    module = {
        "__typename": "ImageModule",
        "id": 1,
        "width": 600,
        "imageSizes": {"size_disp": {"url": url_of("disp", 600)}},
    }

    assert select_image_url(module, None) == (600, url_of("disp", 600))


def test_module_source_is_used_when_no_sizes_are_listed() -> None:
    module = {"__typename": "ImageModule", "id": 1, "width": 555, "src": url_of("source", 555)}

    assert select_image_url(module, None) == (555, url_of("source", 555))


def test_no_usable_url_yields_no_selection() -> None:
    module = {"__typename": "ImageModule", "id": 1, "width": 100, "src": "file:///etc/passwd"}

    assert select_image_url(module, None) is None
    assert candidate_sizes(module) == []


def test_image_asset_names_files_after_the_cdn_basename() -> None:
    asset = image_asset(image_module(1, [variant("1400", 1400, name="abc123")]), "003", None)

    assert asset is not None
    assert asset.file_name == "003_abc123.png"
    assert (asset.width, asset.file_prefix) == (1400, "003")


def test_image_asset_keeps_the_module_caption() -> None:
    module = image_module(1, [variant("1400", 1400)], caption="<div>A boo</div>")

    asset = image_asset(module, "001", None)

    assert asset is not None
    assert asset.caption == "<div>A boo</div>"


def test_image_asset_keeps_the_size_the_page_declares() -> None:
    module = image_module(1, [variant("1400", 1400)], width=600, height=579)

    asset = image_asset(module, "001", None)

    assert asset is not None
    assert (asset.display_width, asset.display_height) == (600, 579)


def test_image_asset_leaves_the_declared_size_empty_when_the_payload_omits_it() -> None:
    module = image_module(1, [variant("1400", 1400)], width="wide", height=None)

    asset = image_asset(module, "001", None)

    assert asset is not None
    assert (asset.display_width, asset.display_height) == (0, 0)


def test_image_asset_reads_a_declared_size_spelled_as_text() -> None:
    module = image_module(1, [variant("1400", 1400)], width="600", height="579")

    asset = image_asset(module, "001", None)

    assert asset is not None
    assert (asset.display_width, asset.display_height) == (600, 579)


def test_image_asset_ignores_an_over_long_display_size() -> None:
    module = image_module(1, [variant("1400", 1400)], width="9" * 5000, height="603")

    asset = image_asset(module, "001", None)

    assert asset is not None
    assert (asset.display_width, asset.display_height) == (0, 603)


def test_image_asset_ignores_a_pixel_size_beyond_its_bound() -> None:
    module = image_module(1, [variant("1400", 1400)], width=10**400, height=603)

    asset = image_asset(module, "001", None)

    assert asset is not None
    assert (asset.display_width, asset.display_height) == (0, 603)


def test_image_asset_sanitizes_a_hostile_cdn_name() -> None:
    module = {
        "__typename": "ImageModule",
        "id": 1,
        "width": 10,
        "imageSizes": {
            "allAvailable": [
                {
                    "url": "https://mir-s3-cdn-cf.behance.net/project_modules/source/a:b|c.png",
                    "width": 10,
                    "type": "JPG",
                }
            ]
        },
    }

    asset = image_asset(module, "001", None)

    assert asset is not None
    assert asset.file_name == "001_a-b-c.png"


def test_plan_gallery_resolves_images_embeds_and_destination(tmp_path: Path) -> None:
    payload = {
        "id": 42,
        "name": "Planned",
        "slug": "Planned-Slug",
        "modules": [
            image_module(1, [variant("source", 900, name="one")]),
            {
                "__typename": "EmbedModule",
                "id": 2,
                "fluidEmbed": '<iframe src="https://embed.example.com/x"></iframe>',
            },
            {
                "__typename": "MediaCollectionModule",
                "id": 3,
                "components": [
                    {"id": 31, "imageSizes": {"allAvailable": [variant("1400", 1400, name="two")]}}
                ],
            },
            {"__typename": "TextModule", "id": 4, "text": "<div>Words</div>"},
        ],
    }
    client = FakeClient(pages={42: store_state_page(payload)})

    plan = plan_gallery(client, "42", None, tmp_path)

    assert plan.destination == tmp_path / "42_Planned-Slug"
    assert [asset.file_name for asset in plan.images] == ["001_one.png", "003_01_two.png"]
    assert [slide.position for slide in plan.slides] == [1, 3]
    assert plan.slides[1].is_collection is True
    assert plan.expected_images == 2
    assert len(plan.embeds) == 1
    assert plan.texts == (TextBlock(position=4, markup="<div>Words</div>"),)


def test_plan_gallery_groups_a_collection_into_one_slide(tmp_path: Path) -> None:
    payload = {
        "id": 61,
        "modules": [
            {
                "__typename": "MediaCollectionModule",
                "id": 1,
                "caption": "<div>Row</div>",
                "fullBleed": 0,
                "components": [
                    {
                        "id": 11,
                        "width": 320,
                        "height": 603,
                        "imageSizes": {"allAvailable": [variant("1400", 1400, name="one")]},
                    },
                    {
                        "id": 12,
                        "width": 320,
                        "height": 603,
                        "imageSizes": {"allAvailable": [variant("1400", 1400, name="two")]},
                    },
                ],
            }
        ],
    }
    client = FakeClient(pages={61: store_state_page(payload)})

    plan = plan_gallery(client, "61", None, tmp_path)

    assert len(plan.slides) == 1
    assert plan.slides[0].is_collection is True
    assert plan.slides[0].collection_caption == "<div>Row</div>"
    assert [asset.file_name for asset in plan.slides[0].images] == [
        "001_01_one.png",
        "001_02_two.png",
    ]


def test_plan_gallery_keeps_the_full_bleed_flag_of_a_slide(tmp_path: Path) -> None:
    payload = {"id": 62, "modules": [image_module(1, [variant("source", 900)], fullBleed=1)]}
    client = FakeClient(pages={62: store_state_page(payload)})

    plan = plan_gallery(client, "62", None, tmp_path)

    assert plan.slides[0].is_full_bleed is True


def test_plan_gallery_wraps_malformed_modules(tmp_path: Path) -> None:
    payload = {
        "id": 7,
        "modules": [{"__typename": "MediaCollectionModule", "id": 1, "components": 5}],
    }
    client = FakeClient(pages={7: store_state_page(payload)})

    with pytest.raises(GalleryError):
        plan_gallery(client, "7", None, tmp_path)


def test_plan_gallery_reports_images_without_variants(tmp_path: Path) -> None:
    payload = {
        "id": 8,
        "modules": [{"__typename": "ImageModule", "id": 1, "width": 10, "src": "file:///a.png"}],
    }
    client = FakeClient(pages={8: store_state_page(payload)})

    plan = plan_gallery(client, "8", None, tmp_path)

    assert plan.images == ()
    assert plan.slides == ()
    assert plan.expected_images == 1


def test_project_folder_name_falls_back_to_the_id() -> None:
    project = GalleryProject(id=9, name="", slug="", modules=(), payload={})

    assert project.folder_name == "9"
