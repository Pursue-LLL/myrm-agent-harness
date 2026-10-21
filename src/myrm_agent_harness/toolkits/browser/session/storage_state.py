"""Storage-state normalisation for re-injecting saved cookies and localStorage into a browser context.

[INPUT]
- (none)

[OUTPUT]
- normalize_cookies: Sanitize Playwright cookies (expires ≤ 0, sameSite Title Case) for safe re-injection
- build_localstorage_script: Build origin-guarded JS for localStorage injection via add_init_script

[POS]
Single normalisation point for the two injection paths: restoring a saved session from the vault
(session_persistence) and carrying live storage over to a new engine (lifecycle restart).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

_SAMESITE_CANONICAL = {"strict": "Strict", "lax": "Lax", "none": "None"}


def normalize_cookies(cookies: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Sanitize cookies exported by Playwright for safe re-injection.

    Playwright ``context.storage_state()`` exports session cookies with
    ``expires: -1`` or ``0``.  When passed back to ``context.add_cookies()``,
    ``expires=0`` is interpreted as *"already expired"* and the cookie is
    silently dropped.  Additionally, ``sameSite`` may arrive in lowercase
    (``none``/``lax``/``strict``) but ``add_cookies`` expects Title Case.
    """
    out: list[dict[str, object]] = []
    for cookie in cookies:
        c = dict(cookie)
        exp = c.get("expires")
        if isinstance(exp, (int, float)) and exp <= 0:
            c.pop("expires", None)
        ss = c.get("sameSite")
        if isinstance(ss, str):
            c["sameSite"] = _SAMESITE_CANONICAL.get(ss.lower(), ss)
        out.append(c)
    return out


def build_localstorage_script(
    items: Sequence[Mapping[str, object]],
    origin: str | None = None,
) -> str:
    """Build JavaScript to set localStorage items with optional origin guard.

    Uses ``JSON.parse`` for safe serialisation (immune to injection via
    malicious key/value content).

    Args:
        items: List of ``{name, value}`` pairs.
        origin: When provided, the script only executes on pages whose
            ``window.location.origin`` matches this value.

    Returns:
        Self-executing JavaScript code string.
    """
    payload = json.dumps(items)
    origin_json = json.dumps(origin) if origin else None

    if origin_json:
        return (
            f"(() => {{\n"
            f"  if (window.location.origin === {origin_json}) {{\n"
            f"    JSON.parse({json.dumps(payload)}).forEach("
            f"({{name, value}}) => localStorage.setItem(name, value));\n"
            f"  }}\n"
            f"}})();"
        )
    return (
        f"(() => {{\n"
        f"  JSON.parse({json.dumps(payload)}).forEach("
        f"({{name, value}}) => localStorage.setItem(name, value));\n"
        f"}})();"
    )
