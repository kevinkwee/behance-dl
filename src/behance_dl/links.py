"""URL rules for the links that author-written prose may carry."""

from __future__ import annotations

import re
import urllib.parse

_LINK_SCHEMES = frozenset({"http", "https"})

_SAFE_LINK_CHARACTERS = ":/?#@!$&'*+,;=%~"
_CONTROL_OR_SPACE = re.compile(r"[\s\x00-\x1f\x7f]")


def safe_link_target(url: str) -> str | None:
    """Return the percent-encoded target for an http or https address with a host, else None."""
    candidate = url.strip()
    if _CONTROL_OR_SPACE.search(candidate):
        return None
    try:
        parts = urllib.parse.urlsplit(candidate)
        if parts.scheme not in _LINK_SCHEMES or not parts.netloc:
            return None
        return urllib.parse.quote(candidate, safe=_SAFE_LINK_CHARACTERS)
    except ValueError:
        # An address a URL parser rejects is not a link, whatever the author intended.
        return None
