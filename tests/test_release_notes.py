"""Tests for the release notes script used by the release workflow."""

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

SAMPLE_WITH_EMPTY_SECTION = """# Changelog

## [1.2.0] - 2026-01-02

## [1.1.0] - 2025-12-01
"""


def load_module() -> ModuleType:
    """Load the release notes script as a module."""
    spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def use_changelog(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    text: str,
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(text, encoding="utf-8")
    monkeypatch.setattr(module, "CHANGELOG", changelog)


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


def test_main_prints_the_notes_for_a_known_version(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    use_changelog(module, monkeypatch, tmp_path, SAMPLE)

    exit_code = module.main(["release_notes.py", "v1.2.0"])

    assert capsys.readouterr().out == "### Added\n\n- A thing.\n"
    assert exit_code == 0


def test_main_prints_nothing_for_a_missing_version(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    use_changelog(module, monkeypatch, tmp_path, SAMPLE)

    exit_code = module.main(["release_notes.py", "v9.9.9"])

    assert capsys.readouterr().out == ""
    assert exit_code == 0


def test_main_reports_a_missing_version_on_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    use_changelog(module, monkeypatch, tmp_path, SAMPLE)

    module.main(["release_notes.py", "v9.9.9"])

    assert "9.9.9" in capsys.readouterr().err


def test_main_prints_nothing_for_a_version_with_an_empty_section(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    use_changelog(module, monkeypatch, tmp_path, SAMPLE_WITH_EMPTY_SECTION)

    module.main(["release_notes.py", "1.2.0"])

    assert capsys.readouterr().out == ""
