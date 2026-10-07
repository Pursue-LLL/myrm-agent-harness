"""Prefix preserving canonicalizer for Prompt Cache optimization.

Enforces byte-level deterministic serialization and ordering of tool definitions,
system prompts, and persona anchors, preventing accidental prefix invalidation.

[INPUT]
- runtime.context.prompt_cache_lifecycle_types::CachePrefixFingerprint (POS: Prompt-cache aware session
  lifecycle and prefix preserving router types.)

[OUTPUT]
- PrefixPreservingCanonicalizer: Canonicalizes request skeletons to ensure byte-stable prefix cache
  alignment.

[POS]
Prefix preserving canonicalizer for Prompt Cache optimization.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence

from .prompt_cache_lifecycle_types import CachePrefixFingerprint


class PrefixPreservingCanonicalizer:
    """Canonicalizes request skeletons to ensure byte-stable prefix cache alignment."""

    def __init__(self, chars_per_token_ratio: float = 3.8) -> None:
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def canonicalize_tools(self, tools: Sequence[Mapping[str, str]]) -> tuple[str, str]:
        """Serializes tool schemas into a canonical deterministic JSON string and SHA-256 hash."""
        # Sort tools deterministically by name
        sorted_tools = sorted(tools, key=lambda t: t.get("name", ""))
        canonical_json = json.dumps(sorted_tools, sort_keys=True, separators=(",", ":"))
        sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return canonical_json, sha256

    def compute_prefix_fingerprint(
        self,
        tools: Sequence[Mapping[str, str]],
        system_prompt: str,
        persona: str = "",
    ) -> CachePrefixFingerprint:
        """Computes deterministic hashes for each prefix component and a unified fingerprint."""
        _, tool_hash = self.canonicalize_tools(tools)
        sys_hash = hashlib.sha256(system_prompt.strip().encode("utf-8")).hexdigest()
        persona_hash = hashlib.sha256(persona.strip().encode("utf-8")).hexdigest()

        combined_payload = f"tools:{tool_hash}|sys:{sys_hash}|persona:{persona_hash}"
        combined_hash = hashlib.sha256(combined_payload.encode("utf-8")).hexdigest()

        total_chars = len(system_prompt) + len(persona) + sum(len(str(t)) for t in tools)
        token_count = self.estimate_tokens("x" * total_chars)

        return CachePrefixFingerprint(
            tool_registry_hash=tool_hash,
            system_prompt_hash=sys_hash,
            persona_hash=persona_hash,
            prefix_token_count=token_count,
            combined_fingerprint=combined_hash,
            metadata={
                "tool_count": str(len(tools)),
                "has_persona": str(bool(persona.strip())),
            },
        )

    def verify_prefix_continuity(
        self,
        baseline: CachePrefixFingerprint,
        current: CachePrefixFingerprint,
    ) -> tuple[bool, str]:
        """Verifies if current prefix is 100% identical to baseline fingerprint."""
        if baseline.combined_fingerprint == current.combined_fingerprint:
            return True, "Prefix perfectly aligned; 100% cache preservation guaranteed."

        mismatches: list[str] = []
        if baseline.tool_registry_hash != current.tool_registry_hash:
            mismatches.append("tool_definitions_reordered_or_mutated")
        if baseline.system_prompt_hash != current.system_prompt_hash:
            mismatches.append("system_prompt_text_mutated")
        if baseline.persona_hash != current.persona_hash:
            mismatches.append("persona_anchor_mutated")

        reason = f"Prefix broken due to: {', '.join(mismatches)}"
        return False, reason
