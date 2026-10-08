"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/graph_parsers.py
[INPUT]: MemOS knowledge graph JSON dumps containing entities, nodes, and relational triples.
[OUTPUT]: MemOSParser extracting structured canonical ExtractedMemoryUnit facts.
"""

from __future__ import annotations

import hashlib
import json

from myrm_agent_harness.toolkits.memory.migration.models import (
    ExtractedMemoryUnit,
    MigrationSourceType,
)
from myrm_agent_harness.toolkits.memory.migration.security_guard import (
    MigrationSecurityGuard,
)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:16]


class MemOSParser:
    """Parses MemOS graph JSON format containing entities, concepts, or triples."""

    def parse(
        self,
        raw_text: str,
        source_id: str,
        guard: MigrationSecurityGuard,
    ) -> list[ExtractedMemoryUnit]:
        units: list[ExtractedMemoryUnit] = []
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return units

        if not isinstance(data, dict):
            return units

        # 1. Parse entities / nodes
        nodes = data.get("nodes") or data.get("entities") or []
        if isinstance(nodes, list):
            for idx, node in enumerate(nodes):
                if not isinstance(node, dict):
                    continue
                name = str(node.get("name") or node.get("label") or node.get("title", "")).strip()
                desc = str(node.get("description") or node.get("content") or "").strip()
                content = f"{name}: {desc}" if desc else name
                if not content:
                    continue

                cleansed = guard.sanitize_text(content)
                entity_type = str(node.get("type", "semantic")).lower()
                layer = (
                    "profile"
                    if "user" in entity_type or "persona" in entity_type
                    else "semantic"
                )
                node_id = str(node.get("id") or f"{source_id}_node_{idx}")
                units.append(
                    ExtractedMemoryUnit(
                        source_type=MigrationSourceType.MEMOS,
                        source_id=node_id,
                        raw_snippet=json.dumps(node, ensure_ascii=False),
                        normalized_text=cleansed,
                        layer=layer,
                        tags=["memos_entity", entity_type],
                        content_hash=_hash_content(cleansed),
                        provenance={"source": "memos_graph", "entity_type": entity_type},
                    )
                )

        # 2. Parse edges / triples
        triples = data.get("triples") or data.get("relations") or []
        if isinstance(triples, list):
            for idx, triple in enumerate(triples):
                if not isinstance(triple, dict):
                    continue
                subj = str(triple.get("subject") or triple.get("head", "")).strip()
                pred = str(triple.get("predicate") or triple.get("relation", "")).strip()
                obj = str(triple.get("object") or triple.get("tail", "")).strip()
                if not (subj and pred and obj):
                    continue

                content = f"{subj} {pred} {obj}"
                cleansed = guard.sanitize_text(content)
                triple_id = str(triple.get("id") or f"{source_id}_rel_{idx}")
                units.append(
                    ExtractedMemoryUnit(
                        source_type=MigrationSourceType.MEMOS,
                        source_id=triple_id,
                        raw_snippet=json.dumps(triple, ensure_ascii=False),
                        normalized_text=cleansed,
                        layer="semantic",
                        tags=["memos_relation", pred.lower()],
                        content_hash=_hash_content(cleansed),
                        provenance={"source": "memos_triple", "relation": pred},
                    )
                )

        return units
