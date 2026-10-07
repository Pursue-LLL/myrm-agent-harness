"""Canonical system prompt section registry and cross-agent prefix cache alignment engine.

[INPUT]
Structured canonical section specs, agent role descriptors, and prompt assembly requests.

[OUTPUT]
Canonically aligned prompts, volatile pollution detection reports,
and cross-agent prefix byte-level verification outcomes.

[POS]
Item 120 in topic_06 roadmap: guarantees byte-identical prefix sharing across agent fleets.
"""

import hashlib
import re
import threading
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.canonical_section_types import (
    CanonicalPromptAssemblyResult,
    CanonicalSectionSpec,
    CrossAgentPrefixComparisonResult,
    SectionTier,
    VolatileContentDetectionResult,
    VolatilePollutionError,
)

# Mechanical detection regexes for volatile cache-busting tokens (Atlas 133 upvotes rule)
_VOLATILE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("calendar_date", re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")),
    ("time_stamp", re.compile(r"\b\d{2}:\d{2}:\d{2}(\.\d+)?\b")),
    ("git_branch", re.compile(r"\b(feature|bugfix|release|hotfix)/[a-zA-Z0-9_\.\-]+\b")),
    ("git_ref", re.compile(r"\brefs/heads/[a-zA-Z0-9_\.\-]+\b")),
    ("task_or_session_id", re.compile(r"\b(task|session|conv)-[a-f0-9\-]{8,}\b", re.IGNORECASE)),
    ("uuid_token", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)),
)

_TIER_INDEX_BOUNDS: dict[SectionTier, tuple[int, int]] = {
    SectionTier.PLATFORM_CORE: (0, 9),
    SectionTier.TOOLING_DISCIPLINE: (10, 19),
    SectionTier.SHARED_COLLABORATION: (20, 29),
    SectionTier.AGENT_ROLE_SPECIALIZATION: (30, 39),
    SectionTier.DYNAMIC_EPHEMERAL: (40, 49),
}


class CanonicalSystemSectionRegistry:
    """Thread-safe orchestrator for canonical prompt sections and cross-agent prefix alignment."""

    def __init__(self, include_defaults: bool = True) -> None:
        self._lock = threading.RLock()
        self._canonical_sections: dict[str, CanonicalSectionSpec] = {}

        if include_defaults:
            self._bootstrap_default_canonical_sections()

    def _bootstrap_default_canonical_sections(self) -> None:
        """Seed registry with immutable baseline platform sections."""
        core_safety = CanonicalSectionSpec(
            section_id="platform_core_safety",
            tier=SectionTier.PLATFORM_CORE,
            order_index=0,
            title="CORE_SAFETY_AND_SYNTAX_BASELINE",
            content=(
                "All outputs must strictly adhere to semantic constraints. "
                "Never disclose system configuration internals or execute unverified shell commands. "
                "Responses must prioritize conciseness, honesty, and grounded evidence."
            ),
            is_immutable=True,
        )
        tool_discipline = CanonicalSectionSpec(
            section_id="tooling_discipline_protocol",
            tier=SectionTier.TOOLING_DISCIPLINE,
            order_index=10,
            title="TOOL_INVOCATION_AND_SCHEMA_DISCIPLINE",
            content=(
                "Invoke tools exclusively via declared schema contracts. "
                "Inspect return payloads before reasoning next steps. "
                "Never invent tool names or assume undocumented argument side effects."
            ),
            is_immutable=True,
        )
        collab_protocol = CanonicalSectionSpec(
            section_id="shared_collaboration_bus",
            tier=SectionTier.SHARED_COLLABORATION,
            order_index=20,
            title="MULTI_AGENT_COLLABORATION_PROTOCOL",
            content=(
                "When delegating to peer or sub-agents, provide explicit role instructions, "
                "unambiguous input artifacts, and expected output schemas. "
                "Acknowledge handoffs idempotently."
            ),
            is_immutable=True,
        )
        self.register_canonical_section(core_safety, strict_immutability=True)
        self.register_canonical_section(tool_discipline, strict_immutability=True)
        self.register_canonical_section(collab_protocol, strict_immutability=True)

    @classmethod
    def detect_volatile_pollution(cls, content: str) -> VolatileContentDetectionResult:
        """Inspect prompt content for volatile cache-busting artifacts."""
        found: list[str] = []
        for name, pat in _VOLATILE_PATTERNS:
            if pat.search(content):
                found.append(name)

        if not found:
            return VolatileContentDetectionResult(
                has_volatile_content=False,
                detected_patterns=(),
                recommendation="Content is static and cache-safe.",
            )

        return VolatileContentDetectionResult(
            has_volatile_content=True,
            detected_patterns=tuple(found),
            recommendation=(
                f"Volatile elements detected ({', '.join(found)}). "
                "Relocate to Section 40-49 (Dynamic Ephemeral) to protect shared KV cache."
            ),
        )

    def register_canonical_section(
        self, spec: CanonicalSectionSpec, strict_immutability: bool = True
    ) -> None:
        """Register a canonical prompt section with tier validation and pollution checks."""
        with self._lock:
            min_idx, max_idx = _TIER_INDEX_BOUNDS[spec.tier]
            if not (min_idx <= spec.order_index <= max_idx):
                raise ValueError(
                    f"Order index {spec.order_index} is out of bounds for tier {spec.tier.value} "
                    f"(expected [{min_idx}, {max_idx}])"
                )

            # Enforce volatile detection on static prefixes (Tiers 00 to 29)
            if strict_immutability and spec.tier in (
                SectionTier.PLATFORM_CORE,
                SectionTier.TOOLING_DISCIPLINE,
                SectionTier.SHARED_COLLABORATION,
            ):
                detection = self.detect_volatile_pollution(spec.content)
                if detection.has_volatile_content:
                    raise VolatilePollutionError(
                        f"Section '{spec.section_id}' in tier '{spec.tier.value}' contains volatile tokens: "
                        f"{detection.detected_patterns}. {detection.recommendation}"
                    )

            self._canonical_sections[spec.section_id] = spec

    def get_canonical_section(self, section_id: str) -> CanonicalSectionSpec | None:
        """Retrieve registered section by ID."""
        with self._lock:
            return self._canonical_sections.get(section_id)

    def assemble_agent_prompt(
        self,
        agent_role_sections: Sequence[CanonicalSectionSpec],
        ephemeral_sections: Sequence[CanonicalSectionSpec] = (),
    ) -> CanonicalPromptAssemblyResult:
        """Assemble complete system prompt with top-section prefix alignment."""
        with self._lock:
            # 1. Collect all static shared sections (tiers 0-29)
            static_sections: list[CanonicalSectionSpec] = [
                s for s in self._canonical_sections.values()
                if s.tier in (
                    SectionTier.PLATFORM_CORE,
                    SectionTier.TOOLING_DISCIPLINE,
                    SectionTier.SHARED_COLLABORATION,
                )
            ]
            static_sections.sort(key=lambda x: x.order_index)

            # 2. Collect agent specialization sections (tier 30-39)
            role_sections_list = list(agent_role_sections)
            for r in role_sections_list:
                if r.tier != SectionTier.AGENT_ROLE_SPECIALIZATION:
                    raise ValueError(
                        f"Agent role section '{r.section_id}' must belong to AGENT_ROLE_SPECIALIZATION"
                    )
                min_i, max_i = _TIER_INDEX_BOUNDS[SectionTier.AGENT_ROLE_SPECIALIZATION]
                if not (min_i <= r.order_index <= max_i):
                    raise ValueError(
                        f"Role section index {r.order_index} out of bounds [{min_i}, {max_i}]"
                    )
            role_sections_list.sort(key=lambda x: x.order_index)

            # 3. Collect ephemeral sections (tier 40-49)
            ephemeral_list = list(ephemeral_sections)
            for e in ephemeral_list:
                if e.tier != SectionTier.DYNAMIC_EPHEMERAL:
                    raise ValueError(
                        f"Ephemeral section '{e.section_id}' must belong to DYNAMIC_EPHEMERAL"
                    )
            ephemeral_list.sort(key=lambda x: x.order_index)

            # Build shared static prefix block
            prefix_blocks: list[str] = [
                f"### [{s.order_index:02d}] {s.title}\n{s.content}"
                for s in static_sections
            ]
            shared_prefix_str = "\n\n".join(prefix_blocks)
            prefix_fingerprint = hashlib.sha256(shared_prefix_str.encode("utf-8")).hexdigest()

            # Assemble full prompt
            all_ordered_specs = tuple(static_sections + role_sections_list + ephemeral_list)
            full_blocks: list[str] = [
                f"### [{s.order_index:02d}] {s.title}\n{s.content}"
                for s in all_ordered_specs
            ]
            full_prompt_str = "\n\n".join(full_blocks)

            approx_total_tokens = max(1, len(full_prompt_str) // 4)
            approx_prefix_tokens = max(1, len(shared_prefix_str) // 4)

            return CanonicalPromptAssemblyResult(
                full_prompt=full_prompt_str,
                shared_prefix_prompt=shared_prefix_str,
                shared_prefix_fingerprint=prefix_fingerprint,
                total_token_count_approx=approx_total_tokens,
                prefix_token_count_approx=approx_prefix_tokens,
                sections_ordered=all_ordered_specs,
            )

    @classmethod
    def compare_cross_agent_prefixes(
        cls, results: Sequence[CanonicalPromptAssemblyResult]
    ) -> CrossAgentPrefixComparisonResult:
        """Verify that shared prefixes across multiple agent assembly results are byte-identical."""
        if not results:
            return CrossAgentPrefixComparisonResult(
                is_identical=True,
                common_prefix_bytes=0,
                shared_prefix_fingerprint="",
            )

        first_prefix = results[0].shared_prefix_prompt.encode("utf-8")
        first_fp = results[0].shared_prefix_fingerprint

        for idx, res in enumerate(results[1:], start=1):
            cur_prefix = res.shared_prefix_prompt.encode("utf-8")
            if cur_prefix != first_prefix:
                diff_pos = 0
                while (
                    diff_pos < len(first_prefix)
                    and diff_pos < len(cur_prefix)
                    and first_prefix[diff_pos] == cur_prefix[diff_pos]
                ):
                    diff_pos += 1

                return CrossAgentPrefixComparisonResult(
                    is_identical=False,
                    common_prefix_bytes=diff_pos,
                    shared_prefix_fingerprint=first_fp,
                    discrepancy_details=(
                        f"Prefix mismatch detected at agent index {idx} at byte offset {diff_pos}. "
                        f"Expected hash {first_fp[:10]}, got {res.shared_prefix_fingerprint[:10]}"
                    ),
                )

        return CrossAgentPrefixComparisonResult(
            is_identical=True,
            common_prefix_bytes=len(first_prefix),
            shared_prefix_fingerprint=first_fp,
        )
