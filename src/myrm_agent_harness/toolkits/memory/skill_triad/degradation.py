"""Provider degradation state observer and fallback inspector.

[POS]
Maintains visible degradation states when external model runtimes or vector stores
fail or are unconfigured. Falls back gracefully to zero-dependency builtin
lexical projection while explicitly reporting substitution reasons in describe().

[INPUT]
- myrm_agent_harness.toolkits.memory.skill_triad.models.DegradedSeverity
- myrm_agent_harness.toolkits.memory.skill_triad.models.DegradedStateReport
- myrm_agent_harness.toolkits.memory.skill_triad.models.ProviderDegradedInfo

[OUTPUT]
- DegradedStateObserver
"""

from __future__ import annotations

from typing import ClassVar

from myrm_agent_harness.toolkits.memory.skill_triad.models import (
    DegradedSeverity,
    DegradedStateReport,
    ProviderDegradedInfo,
)


class DegradedStateObserver:
    """Monitors provider health and constructs visible degradation diagnostics."""

    BUILTIN_FALLBACKS: ClassVar[dict[str, str]] = {
        "embedder": "builtin_tfidf_128d",
        "llm": "deterministic_rules",
        "vector_store": "sqlite_fts5_local",
        "reranker": "lexical_bm25_rrf",
    }

    def __init__(self, known_available_vendors: set[str] | None = None) -> None:
        self._known_available: set[str] = known_available_vendors or {
            "builtin",
            "builtin_tfidf_128d",
            "deterministic_rules",
            "sqlite_fts5_local",
            "lexical_bm25_rrf",
            "local",
        }

    def assess_providers(
        self,
        configured_providers: dict[str, str],
        *,
        strict_mode: bool = False,
    ) -> DegradedStateReport:
        """Inspects configured providers and determines degradation status.

        Args:
            configured_providers: Mapping of provider type (e.g. 'embedder')
                to desired vendor (e.g. 'openai', 'qdrant', 'builtin').
            strict_mode: When True, raises RuntimeError if any provider degrades
                (useful for CI or high-assurance environments).
        """
        provider_infos: list[ProviderDegradedInfo] = []
        any_degraded = False

        for p_type, desired_vendor in configured_providers.items():
            clean_type = p_type.strip().lower()
            clean_vendor = desired_vendor.strip().lower()

            if clean_vendor in self._known_available:
                provider_infos.append(
                    ProviderDegradedInfo(
                        provider_type=clean_type,
                        configured_vendor=clean_vendor,
                        active_vendor=clean_vendor,
                        is_degraded=False,
                        degradation_reason="",
                    )
                )
            else:
                any_degraded = True
                fallback_vendor = self.BUILTIN_FALLBACKS.get(
                    clean_type, "builtin_offline_safe"
                )
                reason = (
                    f"External vendor '{clean_vendor}' unavailable; "
                    f"degraded visibly to zero-dependency '{fallback_vendor}'."
                )

                if strict_mode:
                    raise RuntimeError(
                        f"Strict provider enforcement failed for '{clean_type}': {reason}"
                    )

                provider_infos.append(
                    ProviderDegradedInfo(
                        provider_type=clean_type,
                        configured_vendor=clean_vendor,
                        active_vendor=fallback_vendor,
                        is_degraded=True,
                        degradation_reason=reason,
                    )
                )

        if any_degraded:
            overall = DegradedSeverity.DEGRADED_LEXICAL_FALLBACK
            summary = (
                f"{sum(1 for p in provider_infos if p.is_degraded)} provider(s) "
                "operating in degraded mode with zero-dependency fallback."
            )
        else:
            overall = DegradedSeverity.HEALTHY
            summary = "All memory providers operating nominally."

        return DegradedStateReport(
            overall_status=overall,
            providers=tuple(provider_infos),
            strict_mode=strict_mode,
            summary=summary,
        )
