"""PyPI index probes for publish verify and maintainer sync-lock checks.

[INPUT]
- PyPI JSON API (https://pypi.org/pypi/{package}/{version}/json)

[OUTPUT]
- pypi_package_exists(): whether a package version is indexed
- release_has_compiled_core_extra(): whether release wheel exposes compiled-core extra

[POS]
Shared PyPI index probe helpers for harness distribution gates.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

_COMPILED_CORE_PATTERN = re.compile(r"extra == ['\"]compiled-core['\"]")


def pypi_package_exists(package: str, version: str, *, user_agent: str = "myrm-pypi-index") -> bool:
    """Return True when ``package==version`` is indexed on PyPI."""
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def release_has_compiled_core_extra(version: str, *, user_agent: str = "myrm-pypi-index") -> bool:
    """Return True when the release wheel exposes the ``compiled-core`` optional extra."""
    url = f"https://pypi.org/pypi/myrm-agent-harness/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    info = payload.get("info")
    if not isinstance(info, dict):
        return False
    requires_dist = info.get("requires_dist")
    if not isinstance(requires_dist, list):
        return False
    return any(isinstance(req, str) and _COMPILED_CORE_PATTERN.search(req) for req in requires_dist)
