"""Tests for the `py.typed` marker that type checkers read."""

from __future__ import annotations

from importlib.resources import files


def test_py_typed_marker_exists_in_the_package() -> None:
    assert files("behance_dl").joinpath("py.typed").is_file()
