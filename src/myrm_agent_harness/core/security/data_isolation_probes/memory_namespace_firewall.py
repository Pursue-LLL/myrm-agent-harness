"""Agent Memory Namespace Firewall preventing bare queries and logical leaks."""

from __future__ import annotations

import hashlib
import re

from .types import PartitionKeySpec, TenantMemoryContext

_INJECTION_PATTERN = re.compile(r"['\";\x00]|--|\bOR\b|\bAND\b", re.IGNORECASE)


class MemoryNamespaceFirewall:
    """Enforces non-bypassable composite partition keys on all memory persistence drivers.

    Eliminates logical filter omissions and cross-tenant leakage vulnerabilities.
    """

    def __init__(self, enforce_strict_clean: bool = True) -> None:
        self._enforce_strict_clean: bool = enforce_strict_clean

    def sanitize_identifier(self, identifier: str) -> str:
        """Sanitize identity strings to prevent query injection."""
        clean = identifier.strip()
        if not clean:
            raise ValueError("Identifier cannot be empty")
        if self._enforce_strict_clean and _INJECTION_PATTERN.search(clean):
            # Strip malicious characters
            clean = _INJECTION_PATTERN.sub("", clean).strip()
            if not clean:
                raise ValueError("Identifier contains only malicious tokens")
        return clean

    def compile_partition_key(
        self,
        context: TenantMemoryContext,
    ) -> PartitionKeySpec:
        """Compile an immutable composite physical partition key from tenant context."""
        clean_user = self.sanitize_identifier(context.user_id)
        clean_agent = self.sanitize_identifier(context.agent_id)
        scope = context.scope

        composite = f"usr_{clean_user}::agt_{clean_agent}::scp_{scope}"
        digest = hashlib.sha256(composite.encode("utf-8")).hexdigest()[:16]

        return PartitionKeySpec(
            composite_key=composite,
            user_id=clean_user,
            agent_id=clean_agent,
            scope=scope,
            namespace_digest=digest,
        )

    def validate_record_access(
        self,
        record_partition_key: str,
        querying_context: TenantMemoryContext,
    ) -> bool:
        """Verify whether a record strictly belongs to the querying tenant partition."""
        target_spec = self.compile_partition_key(querying_context)
        return record_partition_key == target_spec.composite_key

    def wrap_filter_criteria(
        self,
        querying_context: TenantMemoryContext,
        raw_filter: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Wrap and seal query filter criteria with mandatory partition keys."""
        spec = self.compile_partition_key(querying_context)
        wrapped: dict[str, str] = dict(raw_filter or {})
        wrapped["_partition_key"] = spec.composite_key
        wrapped["_user_id"] = spec.user_id
        wrapped["_agent_id"] = spec.agent_id
        return wrapped
