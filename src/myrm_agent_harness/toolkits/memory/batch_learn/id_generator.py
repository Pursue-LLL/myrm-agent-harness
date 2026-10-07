"""[POS]: src/myrm_agent_harness/toolkits/memory/batch_learn/id_generator.py
[INPUT]: Scope, sub-scope, category, and raw text strings.
[OUTPUT]: Deterministic, collision-resistant NamespacedMemoryId instances with parsing verification.
"""

import hashlib
import re

from myrm_agent_harness.toolkits.memory.batch_learn.models import NamespacedMemoryId


class NamespacedIdGenerator:
    """Industrial-grade namespaced ID generator ensuring cross-session uniqueness and unambiguous provenance."""

    _ID_PATTERN = re.compile(r"^mem:([a-zA-Z0-9_\-\.]+):([a-zA-Z0-9_\-\.]+):([a-zA-Z0-9_\-\.]+):([a-f0-9]{12,32})$")

    @classmethod
    def compute_fingerprint(cls, content: str) -> str:
        """Derive a deterministic 16-character SHA-256 fingerprint from canonicalized content."""
        canonical = content.strip().lower()
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def generate(
        cls,
        scope: str,
        sub_scope: str,
        category: str,
        content: str,
    ) -> NamespacedMemoryId:
        """Construct a structured NamespacedMemoryId from scope metadata and content text."""
        fp = cls.compute_fingerprint(content)
        sanitized_scope = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", scope.strip()) or "default"
        sanitized_sub = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", sub_scope.strip()) or "global"
        sanitized_cat = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", category.strip()) or "general"
        return NamespacedMemoryId.create(
            scope=sanitized_scope,
            sub_scope=sanitized_sub,
            category=sanitized_cat,
            content_fingerprint=fp,
        )

    @classmethod
    def parse(cls, full_id: str) -> NamespacedMemoryId | None:
        """Parse and validate a full namespaced ID string into structured components."""
        match = cls._ID_PATTERN.match(full_id.strip())
        if not match:
            return None
        scope, sub_scope, category, fp = match.groups()
        return NamespacedMemoryId(
            scope=scope,
            sub_scope=sub_scope,
            category=category,
            content_fingerprint=fp,
            full_id=full_id.strip(),
        )

    @classmethod
    def is_valid(cls, full_id: str) -> bool:
        """Return True if the ID strictly matches canonical memory namespacing conventions."""
        return cls._ID_PATTERN.match(full_id.strip()) is not None
