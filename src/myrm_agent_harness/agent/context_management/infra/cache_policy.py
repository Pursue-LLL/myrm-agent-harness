"""Prompt cache policy resolution for context pruning.

[INPUT]
- infra.schemas::CacheTtlPruneConfig (POS: Cache TTL prune configuration)

[OUTPUT]
- CacheTtlPrunePolicy: Resolved cache policy for a model.
- CacheTtlPrunePolicyProfile: Built-in provider profile with calibration metadata.
- resolve_cache_ttl_prune_policy: Resolve provider/model policy without business coupling.

[POS]
Framework-level cache policy resolver. Keeps default behavior conservative while
allowing business layers to inject model-aware context pruning behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import CacheTtlPruneConfig


@dataclass(frozen=True, slots=True)
class CacheTtlPrunePolicy:
    """Resolved cache TTL prune policy for a model family."""

    model_family: str
    config: CacheTtlPruneConfig
    reason: str
    source_url: str = ""
    calibrated_at: str = ""


@dataclass(frozen=True, slots=True)
class CacheTtlPrunePolicyProfile:
    """Built-in provider-neutral matching profile calibrated from provider docs."""

    model_family: str
    patterns: tuple[str, ...]
    config: CacheTtlPruneConfig
    reason: str
    source_url: str
    calibrated_at: str


_DEFAULT_POLICY = CacheTtlPrunePolicy(
    model_family="default",
    config=CacheTtlPruneConfig(),
    reason="default_conservative_cache_ttl",
    calibrated_at="2026-05-19",
)

_POLICY_PROFILES: tuple[CacheTtlPrunePolicyProfile, ...] = (
    CacheTtlPrunePolicyProfile(
        model_family="anthropic",
        patterns=("anthropic", "claude"),
        config=CacheTtlPruneConfig(
            ttl_seconds=300.0,
            soft_trim_ratio=0.25,
            hard_clear_ratio=0.45,
            min_prunable_tokens=8_000,
        ),
        reason="anthropic_short_cache_ttl_profile",
        source_url="https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching",
        calibrated_at="2026-05-19",
    ),
    CacheTtlPrunePolicyProfile(
        model_family="google",
        patterns=("google", "gemini"),
        config=CacheTtlPruneConfig(
            ttl_seconds=3600.0,
            soft_trim_ratio=0.40,
            hard_clear_ratio=0.65,
            min_prunable_tokens=10_000,
        ),
        reason="google_explicit_cache_default_ttl_profile",
        source_url="https://ai.google.dev/gemini-api/docs/caching",
        calibrated_at="2026-05-19",
    ),
    CacheTtlPrunePolicyProfile(
        model_family="openai",
        patterns=("openai", "gpt-"),
        config=CacheTtlPruneConfig(
            ttl_seconds=600.0,
            soft_trim_ratio=0.35,
            hard_clear_ratio=0.55,
            min_prunable_tokens=12_500,
        ),
        reason="openai_in_memory_cache_eviction_profile",
        source_url="https://platform.openai.com/docs/guides/prompt-caching",
        calibrated_at="2026-05-19",
    ),
    CacheTtlPrunePolicyProfile(
        model_family="deepseek",
        patterns=("deepseek",),
        config=CacheTtlPruneConfig(
            ttl_seconds=3600.0,
            soft_trim_ratio=0.40,
            hard_clear_ratio=0.65,
            min_prunable_tokens=12_500,
        ),
        reason="deepseek_best_effort_disk_cache_profile",
        source_url="https://api-docs.deepseek.com/guides/kv_cache",
        calibrated_at="2026-05-19",
    ),
    CacheTtlPrunePolicyProfile(
        model_family="qwen",
        patterns=("qwen", "dashscope"),
        config=CacheTtlPruneConfig(
            ttl_seconds=300.0,
            soft_trim_ratio=0.30,
            hard_clear_ratio=0.50,
            min_prunable_tokens=12_500,
        ),
        reason="qwen_explicit_cache_ttl_profile",
        source_url="https://www.alibabacloud.com/help/en/model-studio/context-cache",
        calibrated_at="2026-05-19",
    ),
)


def resolve_cache_ttl_prune_policy(
    model_name: str | None,
    *,
    override: CacheTtlPruneConfig | None = None,
) -> CacheTtlPrunePolicy:
    """Resolve cache TTL pruning policy for the given model name.

    The resolver intentionally keeps provider values conservative unless the
    caller injects an explicit override. That preserves framework portability:
    harness owns policy mechanics, while product/server layers may provide
    deployment-specific tuning.
    """
    if override is not None:
        return CacheTtlPrunePolicy(
            model_family="override",
            config=override,
            reason="explicit_override",
            calibrated_at="caller_supplied",
        )

    normalized = (model_name or "").lower()
    for profile in _POLICY_PROFILES:
        if any(pattern in normalized for pattern in profile.patterns):
            return CacheTtlPrunePolicy(
                model_family=profile.model_family,
                config=profile.config,
                reason=profile.reason,
                source_url=profile.source_url,
                calibrated_at=profile.calibrated_at,
            )

    return _DEFAULT_POLICY
