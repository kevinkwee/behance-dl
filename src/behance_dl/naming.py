"""Turning remote and user-supplied text into safe file names."""

from __future__ import annotations

import re

UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str, fallback: str) -> str:
    """Reduce arbitrary text to one file name component that cannot escape a folder."""
    return UNSAFE_CHARACTERS.sub("-", value).strip(".-") or fallback


def is_plain_file_name(value: str) -> bool:
    """Report whether text is a single safe file name rather than a path."""
    return bool(value) and value not in {".", ".."} and UNSAFE_CHARACTERS.search(value) is None
