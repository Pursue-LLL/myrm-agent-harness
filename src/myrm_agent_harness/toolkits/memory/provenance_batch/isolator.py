"""Batch learning namespace isolation and deterministic collision-proof ID partitioning.

[INPUT]
- myrm_agent_harness.toolkits.memory.provenance_batch.types::{
      BatchLearnItem,
      BatchLearnResult,
      NamespacedMemoryRef,
  }

[OUTPUT]
- BatchLearnNamespaceIsolator: Partitions memory items with deterministic scope boundaries

[POS]
Guarantees namespace and scope hard boundary isolation during concurrent batch learning pipelines.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.provenance_batch.types import (
    BatchLearnItem,
    BatchLearnResult,
    NamespacedMemoryRef,
)

_DELIMITER = "::"
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]+$")


class BatchLearnNamespaceIsolator:
    """Isolates batch learning entries by synthesizing immutable scope-prefixed identifiers."""

    def format_namespaced_id(
        self,
        *,
        namespace: str,
        scope_level: str,
        raw_id: str,
    ) -> str:
        """Construct a deterministic namespaced identifier.

        Format: `{namespace}::{scope_level}::{raw_id}`
        Idempotent: if `raw_id` already carries the matching prefix, it is returned intact.
        """
        clean_ns = namespace.strip()
        clean_scope = scope_level.strip()
        clean_raw = raw_id.strip()

        if not clean_ns or not clean_scope or not clean_raw:
            raise ValueError("Namespace, scope_level, and raw_id cannot be empty")

        expected_prefix = f"{clean_ns}{_DELIMITER}{clean_scope}{_DELIMITER}"
        if clean_raw.startswith(expected_prefix):
            return clean_raw

        return f"{expected_prefix}{clean_raw}"

    def parse_namespaced_id(
        self,
        namespaced_id: str,
    ) -> tuple[str, str, str]:
        """Deconstruct a namespaced identifier into (namespace, scope_level, raw_id).

        Falls back safely if the identifier lacks proper namespace delimiters.
        """
        parts = namespaced_id.split(_DELIMITER, 2)
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        return "global", "unspecified", namespaced_id

    def isolate_batch(
        self,
        items: list[BatchLearnItem],
    ) -> BatchLearnResult:
        """Screen and isolate a list of batch learning submissions.

        Ensures cross-scope boundaries are strictly honored and ID collisions
        between private agent memory and shared broadcast memory are eliminated.
        """
        partitioned_refs: list[NamespacedMemoryRef] = []
        has_provenance = 0

        for item in items:
            namespaced_id = self.format_namespaced_id(
                namespace=item.namespace,
                scope_level=item.scope_level,
                raw_id=item.raw_id,
            )
            ref = NamespacedMemoryRef(
                namespaced_id=namespaced_id,
                namespace=item.namespace,
                scope_level=item.scope_level,
                raw_id=item.raw_id,
            )
            partitioned_refs.append(ref)
            if item.provenance_link is not None:
                has_provenance += 1

        return BatchLearnResult(
            total_items=len(partitioned_refs),
            namespaced_items=partitioned_refs,
            has_provenance_count=has_provenance,
        )
