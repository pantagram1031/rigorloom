"""Open editor v2 in a browser test.

The v1 screens stay the default until the switch; a test that drives the
editor v2 shell asks for it with `?ui=v2` (desktop/src/uiVariant.ts).
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def editor_v2_url(url: str) -> str:
    """`url` with `ui=v2` in its query, keeping any other parameters."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "ui"]
    query.append(("ui", "v2"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))
