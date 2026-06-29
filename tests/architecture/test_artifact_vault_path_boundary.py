"""Architecture gate: forbid brand-specific artifact vault path literals in harness src."""

from __future__ import annotations

from pathlib import Path

import pytest

HARNESS_SRC = Path(__file__).resolve().parents[2] / "src" / "myrm_agent_harness"

_FORBIDDEN_LITERALS: tuple[str, ...] = (".myrm/vault",)


@pytest.mark.architecture
def test_harness_src_has_no_legacy_myrm_vault_literals() -> None:
    offenders: list[str] = []
    for path in HARNESS_SRC.rglob("*"):
        if path.suffix not in {".py", ".md", ".ts", ".tsx"}:
            continue
        if path.is_dir():
            continue
        text = path.read_text(encoding="utf-8")
        for literal in _FORBIDDEN_LITERALS:
            if literal in text:
                offenders.append(f"{path.relative_to(HARNESS_SRC)}: contains {literal!r}")
    assert not offenders, "Legacy vault path literals found:\n" + "\n".join(offenders)
