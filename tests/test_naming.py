"""Tests for the file naming rules."""

from __future__ import annotations

import pytest

from behance_dl.naming import is_plain_file_name, safe_name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain-name_1.png", "plain-name_1.png"),
        ("with space.png", "with-space.png"),
        ("../../escape", "escape"),
        ("a:b|c?d*e", "a-b-c-d-e"),
        (".", ""),
        ("..", ""),
        ("", ""),
    ],
)
def test_safe_name_reduces_text_to_one_component(value: str, expected: str) -> None:
    assert safe_name(value, "") == expected


def test_safe_name_uses_the_fallback_when_nothing_is_left() -> None:
    assert safe_name("...", "image") == "image"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("001_abc.png", True),
        ("sub/001_abc.png", False),
        ("sub\\001_abc.png", False),
        ("..", False),
        (".", False),
        ("", False),
        ("001_a\u0000.png", False),
    ],
)
def test_is_plain_file_name(value: str, expected: bool) -> None:
    assert is_plain_file_name(value) is expected
