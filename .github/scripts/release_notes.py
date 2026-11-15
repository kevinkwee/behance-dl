"""Print the changelog section for one version, so a release can use it as its notes."""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def section(version: str, changelog: str) -> str:
    """Return the body of the section for a version, without its heading or link block."""
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[[^\]]*\]|^\[[^\]]+\]:|\Z)"
    match = re.search(pattern, changelog, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def main(argv: list[str]) -> int:
    """Print the notes for the version named by the first argument."""
    if len(argv) < 2:
        print("usage: release_notes.py <tag>", file=sys.stderr)
        return 2
    version = argv[1].strip().lstrip("v")
    print(section(version, CHANGELOG.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
