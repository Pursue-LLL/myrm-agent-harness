"""Unit tests for wiki canonical registry helpers."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.canonical_registry import (
    build_canonical_index,
    compute_page_lease_hash,
    derive_canonical_id,
    find_canonical_conflict,
    stamp_content_hash,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


def test_derive_canonical_id_from_nested_path() -> None:
    assert derive_canonical_id("research/react-hooks") == "research.react-hooks"


def test_build_index_and_detect_alias_conflict(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    path = structure.get_concept_file_path("topics/react-hooks")
    path.write_text(
        "---\ntype: concept\naliases:\n  - React Hooks\n---\n## Compiled Truth\nBody\n",
        encoding="utf-8",
    )
    index = build_canonical_index(structure)
    conflict = find_canonical_conflict(
        index,
        concept_name="notes/hooks-guide",
        canonical_id=None,
        aliases=("React Hooks",),
    )
    assert conflict == "topics/react-hooks"


def test_page_lease_hash_stable_when_content_hash_stamped() -> None:
    raw = "---\ntype: session\n---\n## Compiled Truth\nHello\n"
    before = compute_page_lease_hash(raw)
    stamped = stamp_content_hash(raw)
    after = compute_page_lease_hash(stamped)
    assert before == after
