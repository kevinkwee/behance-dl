"""Tests for the changelog slicing used by the release workflow."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "release_notes.py"

SAMPLE = """# Changelog

## [Unreleased]

## [1.2.0] - 2026-01-02

### Added

- A thing.

## [1.1.0] - 2025-12-01

### Fixed

- A bug.
"""


def load_module() -> ModuleType:
    """Load the release notes script as a module."""
    spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_section_returns_the_body_of_one_version() -> None:
    module = load_module()

    body = module.section("1.2.0", SAMPLE)

    assert "### Added" in body
    assert "A thing." in body
    assert "A bug." not in body
    assert "2026-01-02" not in body


def test_section_of_the_oldest_version_stops_at_the_links() -> None:
    module = load_module()
    sample = SAMPLE + "\n[1.2.0]: https://example.com\n"
    body = module.section("1.1.0", sample)

    assert body.strip() == "### Fixed\n\n- A bug."


def test_section_returns_nothing_for_an_unknown_version() -> None:
    module = load_module()

    assert module.section("9.9.9", SAMPLE) == ""
    assert module.section("", SAMPLE) == ""


def test_main_requires_a_tag(capsys: pytest.CaptureFixture[str]) -> None:
    module = load_module()

    assert module.main(["release_notes.py"]) == 2
    assert "usage" in capsys.readouterr().err
