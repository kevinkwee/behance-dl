"""Tests for the URL rules author-written links must pass."""

from __future__ import annotations

import pytest

from behance_dl.links import safe_link_target


def test_safe_link_target_keeps_an_https_address() -> None:
    assert safe_link_target("https://embed.figma.com/x") == "https://embed.figma.com/x"


def test_safe_link_target_keeps_an_http_address() -> None:
    assert safe_link_target("http://example.test/a") == "http://example.test/a"


def test_safe_link_target_percent_encodes_unsafe_characters() -> None:
    assert safe_link_target("https://x.test/](a)") == "https://x.test/%5D%28a%29"


def test_safe_link_target_trims_surrounding_space() -> None:
    assert safe_link_target("  https://x.test/a  ") == "https://x.test/a"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///C:/Windows/win.ini",
        "data:text/html,<script>alert(1)</script>",
        "//x.test/a",
        "https:///x",
        "",
    ],
)
def test_safe_link_target_rejects_an_address_this_document_will_not_open(url: str) -> None:
    assert safe_link_target(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://x.test/a b",
        "https://x.test/a\tb",
        "https://x.test/a\nb",
        "https://x.test/a\x00b",
        "https://x.test/a\x7fb",
    ],
)
def test_safe_link_target_rejects_whitespace_and_control_characters(url: str) -> None:
    assert safe_link_target(url) is None


@pytest.mark.parametrize("url", ["http://[", "https://[notip]/", "https://x.test/\ud800"])
def test_safe_link_target_rejects_an_address_the_parser_or_encoder_refuses(url: str) -> None:
    assert safe_link_target(url) is None
