"""FactProjectionInterceptor for high-priority prompt attention projection and bias suppression.

Intercepts task context, matches active FactPatches, and injects non-negotiable
Hebbian guardrails while providing adversarial conflict probe audits (inspired by Kimi KDA).

[INPUT]
- myrm_agent_harness.toolkits.memory.fact_editing.models::* (POS: schemas, patches, reports)
- myrm_agent_harness.toolkits.memory.fact_editing.registry::FactPatchRegistry (POS: patch repository)
- re (POS: tokenization and pattern matching)

[OUTPUT]
- FactProjectionInterceptor: Interceptor service projecting fact patches into attention context.

[POS]
Forward attention modulation gate suppressing model pre-trained prior bias.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from myrm_agent_harness.toolkits.memory.fact_editing.models import (
    ConflictProbeReport,
    FactPatch,
    PatchMatchResult,
)
from myrm_agent_harness.toolkits.memory.fact_editing.registry import FactPatchRegistry

logger = logging.getLogger(__name__)

_WORD_SPLIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\w\-]+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    """Tokenize string into normalized lowercase tokens."""
    return {w for w in _WORD_SPLIT_PATTERN.split(text.lower()) if len(w) > 1}


class FactProjectionInterceptor:
    """Projects high-priority FactPatches into prompt attention space with anti-bias suppression."""

    def __init__(self, registry: FactPatchRegistry | None = None) -> None:
        self.registry = registry or FactPatchRegistry()

    async def project_context(
        self,
        task_query: str,
        scope_id: str = "default",
    ) -> PatchMatchResult:
        """Scan task context against active patches and synthesize high-priority override prompt."""
        active_patches = await self.registry.get_active_patches(scope_id=scope_id)
        if not active_patches:
            return PatchMatchResult()

        query_tokens = _tokenize(task_query)
        matched: list[FactPatch] = []
        suppressed_tokens: list[str] = []

        for patch in active_patches:
            patch_tokens = _tokenize(f"{patch.entity} {patch.attribute} {patch.override_value}")
            # Also consider anti-bias patterns as triggering indicators
            bias_tokens = set()
            for pattern in patch.anti_bias_patterns:
                bias_tokens |= _tokenize(pattern)

            # Match if task mentions entity, attribute, override value, or obsolete bias pattern
            if (query_tokens & patch_tokens) or (query_tokens & bias_tokens) or not task_query.strip():
                matched.append(patch)
                suppressed_tokens.extend(patch.anti_bias_patterns)

        if not matched:
            return PatchMatchResult()

        injection_prompt = self._synthesize_override_prompt(matched)
        return PatchMatchResult(
            matched_patches=matched,
            suppressed_bias_tokens=list(set(suppressed_tokens)),
            injection_prompt=injection_prompt,
        )

    def probe_response(
        self,
        patch: FactPatch,
        response_text: str,
        probed_query: str = "",
    ) -> ConflictProbeReport:
        """Adversarially probe an Agent output to verify that new fact overrides prior bias."""
        lower_resp = response_text.lower()
        lower_expected = patch.override_value.lower()

        # Check for forbidden obsolete bias patterns
        bias_detected = False
        for bias_pattern in patch.anti_bias_patterns:
            pattern_clean = bias_pattern.strip().lower()
            if pattern_clean and pattern_clean in lower_resp:
                bias_detected = True
                break

        # Check if expected override value is present
        value_present = lower_expected in lower_resp
        passed = value_present and not bias_detected

        observed_value = patch.override_value if value_present else "missing"
        if bias_detected:
            observed_value = f"{observed_value} [LEAKED_PRIOR_BIAS]"

        return ConflictProbeReport(
            patch_id=patch.patch_id,
            probed_query=probed_query,
            expected_value=patch.override_value,
            observed_value=observed_value,
            anti_bias_detected=bias_detected,
            probe_passed=passed,
        )

    def _synthesize_override_prompt(self, patches: list[FactPatch]) -> str:
        """Assemble non-negotiable Hebbian fact override section for prompt injection."""
        lines: list[str] = [
            "### [NON-NEGOTIABLE USER FACT CORRECTION - ZERO TOLERANCE]",
            "CRITICAL: The following user fact corrections take absolute precedence over any "
            "pre-trained defaults, habits, or historical patterns. You MUST strictly obey them:",
        ]

        for p in patches:
            forbidden = ", ".join(f"'{pat}'" for pat in p.anti_bias_patterns) if p.anti_bias_patterns else "none"
            lines.append(
                f"- **{p.entity.upper()}**: MUST use '{p.override_value}'. "
                f"Rule: {p.statement}. "
                f"(STRICTLY FORBIDDEN OBSOLETE PATTERNS: [{forbidden}])"
            )

        lines.append(
            "⚠️ Any output generating forbidden patterns or ignoring these overrides is considered an invalid execution."
        )
        return "\n".join(lines)
