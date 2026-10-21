"""Exception hierarchy integrity guard.

Ensures the browser exception tree stays truthful: every *leaf* exception
class must have at least one consumption site (raise, except, or isinstance)
somewhere in the codebase.  Leaf classes with zero consumption are dead API —
they read as usable to maintainers (e.g. ``except BrowserClosedError``) but
can never fire.  Keeping them documented as part of the hierarchy is a
maintenance trap, so the test fails before such classes are introduced again.

Parent classes (nodes with subclasses) are exempt: their value is semantic
grouping for ``except Parent`` / ``isinstance(exc, Parent)`` dispatch.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from myrm_agent_harness.toolkits.browser.exceptions import BrowserError

# The exception definition module is excluded: docstring usage examples and
# class bodies live there and would otherwise count as spurious consumption.
_DEFINITION_MODULE = "exceptions.py"


def _leaf_exception_classes() -> dict[str, type[BrowserError]]:
    """Return all BrowserError leaf classes (no subclasses)."""
    leaves: dict[str, type[BrowserError]] = {}

    def walk(cls: type[BrowserError]) -> None:
        subs = cls.__subclasses__()
        if not subs:
            leaves[cls.__name__] = cls
            return
        for sub in subs:
            walk(sub)

    walk(BrowserError)
    return leaves


def _consumption_patterns(cls_name: str) -> list[re.Pattern[str]]:
    """Regex patterns that count as a consumption site for cls_name."""
    return [
        re.compile(rf"raise {cls_name}\s*\("),
        re.compile(rf"error = {cls_name}\s*\("),
        re.compile(rf"except {cls_name}\s*:"),
        re.compile(rf"except {cls_name}\s+as\b"),
        re.compile(rf"isinstance\([^)]*\b{cls_name}\b[^)]*\)"),
    ]


class TestBrowserExceptionHierarchy:
    def test_every_leaf_class_has_a_consumption_site(self) -> None:
        """Dead leaf classes must not creep back into the hierarchy."""
        harness_root = Path(__file__).resolve().parents[3]
        src_root = harness_root / "src"

        dead: list[str] = []
        for cls_name in sorted(_leaf_exception_classes()):
            patterns = _consumption_patterns(cls_name)
            found = False
            for dirpath, _dirnames, filenames in os.walk(src_root):
                for filename in filenames:
                    if not filename.endswith(".py"):
                        continue
                    if filename == _DEFINITION_MODULE and Path(dirpath).name == "browser":
                        continue
                    path = Path(dirpath) / filename
                    text = path.read_text(encoding="utf-8")
                    if any(pattern.search(text) for pattern in patterns):
                        found = True
                        break
                if found:
                    break
            if not found:
                dead.append(cls_name)

        assert dead == [], (
            f"Browser exception leaf classes with zero consumption sites: {dead}. "
            "Either add a raise/except/isinstance site or delete the class."
        )
