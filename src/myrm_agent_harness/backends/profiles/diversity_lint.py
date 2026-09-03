"""Provider Diversity Linter and Root Vendor Extraction.

Validates provider heterogeneity across multi-model agent configurations,
Mixture-of-Agents (MoA) overlays, and Pareto frontier profile presets.

[INPUT]
- Model identifiers (e.g. "openai/gpt-4o", "anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat")
- Provider identifiers (e.g. "openai", "azure-openai", "openrouter", "siliconflow")

[OUTPUT]
- extract_root_vendor: extracts the true underlying vendor (e.g. azure-openai -> openai, openrouter/anthropic/claude -> anthropic)
- validate_provider_diversity: checks whether the given selections contain >= min_distinct_vendors unique vendors
- ProviderDiversityResult: structured result with vendor count, root vendors list, and pass status

[POS]
Harness framework layer utility for multi-model diversity verification.
Enforces that advisor teams, MoA overlays, and Pareto presets maintain true
vendor heterogeneity (>= 2 distinct providers) to eliminate single-vendor bias and outage risks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Normalization map for known provider wrappers/proxies to root vendor
_PROVIDER_ROOT_VENDOR_MAP: dict[str, str] = {
    "azure-openai": "openai",
    "azure_openai": "openai",
    "azure": "openai",
    "openai": "openai",
    "openai-codex": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "deepseek": "deepseek",
    "google": "google",
    "gemini": "google",
    "meta": "meta",
    "meta-llama": "meta",
    "mistral": "mistral",
    "mistralai": "mistral",
    "qwen": "qwen",
    "alibaba": "qwen",
    "xai": "xai",
    "grok": "xai",
    "groq": "groq",
    "together": "together",
    "togetherai": "together",
    "siliconflow": "siliconflow",
    "openrouter": "openrouter",
    "ollama": "local",
    "lmstudio": "local",
    "vllm": "local",
}

# Prefix tokens that identify vendors when model strings are formatted as "vendor/model"
_MODEL_PREFIX_VENDOR_MAP: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "deepseek": "deepseek",
    "deepseek-ai": "deepseek",
    "google": "google",
    "gemini": "google",
    "meta": "meta",
    "meta-llama": "meta",
    "mistral": "mistral",
    "mistralai": "mistral",
    "qwen": "qwen",
    "alibaba": "qwen",
    "xai": "xai",
    "grok": "xai",
    "cohere": "cohere",
    "moonshot": "moonshot",
    "zhipu": "zhipu",
    "glm": "zhipu",
    "baichuan": "baichuan",
    "minimax": "minimax",
}


def extract_root_vendor(provider_id: str | None, model: str | None = None) -> str:
    """Extract the canonical underlying root vendor from provider and model strings.

    Handles proxy routers (OpenRouter, SiliconFlow, Together) by inspecting the model prefix,
    while mapping known provider aliases (e.g. azure-openai -> openai) to their root vendor.
    """
    clean_provider = (provider_id or "").strip().lower()
    clean_model = (model or "").strip().lower()

    # 1. If provider is a known multi-vendor aggregator, inspect model prefix first
    if clean_provider in ("openrouter", "siliconflow", "together", "togetherai", "groq"):
        if "/" in clean_model:
            model_vendor_prefix = clean_model.split("/")[0].strip()
            if model_vendor_prefix in _MODEL_PREFIX_VENDOR_MAP:
                return _MODEL_PREFIX_VENDOR_MAP[model_vendor_prefix]

    # 2. Check model string for explicit vendor prefixes even without provider
    if "/" in clean_model:
        model_vendor_prefix = clean_model.split("/")[0].strip()
        if model_vendor_prefix in _MODEL_PREFIX_VENDOR_MAP:
            return _MODEL_PREFIX_VENDOR_MAP[model_vendor_prefix]

    # 3. Model family heuristics from model name
    if clean_model.startswith(("gpt-", "o1-", "o3-", "text-embedding-")):
        return "openai"
    if clean_model.startswith(("claude-", "claude")):
        return "anthropic"
    if clean_model.startswith(("deepseek-", "deepseek")):
        return "deepseek"
    if clean_model.startswith(("gemini-", "gemma-")):
        return "google"
    if clean_model.startswith(("qwen-", "qwen2", "qwq-")):
        return "qwen"
    if clean_model.startswith(("llama-", "llama3", "llama2")):
        return "meta"
    if clean_model.startswith(("mistral-", "codestral-", "mixtral-")):
        return "mistral"
    if clean_model.startswith(("grok-", "grok")):
        return "xai"

    # 4. Fallback to provider root map
    if clean_provider in _PROVIDER_ROOT_VENDOR_MAP:
        return _PROVIDER_ROOT_VENDOR_MAP[clean_provider]

    # 5. Default fallback
    return clean_provider if clean_provider else (clean_model if clean_model else "unknown")


@dataclass(frozen=True, slots=True)
class ModelSelectionSlot:
    """Represents a single model slot in a multi-model configuration."""

    provider_id: str
    model: str
    slot_name: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderDiversityResult:
    """Result of provider diversity validation."""

    is_valid: bool
    distinct_vendor_count: int
    distinct_vendors: tuple[str, ...]
    slots_evaluated: int
    reason: str = ""


def validate_provider_diversity(
    selections: Sequence[ModelSelectionSlot | dict[str, object] | tuple[str, str]],
    *,
    min_distinct_vendors: int = 2,
) -> ProviderDiversityResult:
    """Validate that the given set of model selections satisfies vendor diversity.

    Args:
        selections: A sequence of ModelSelectionSlot, dicts (with providerId/provider and model keys),
                    or (provider_id, model) tuples.
        min_distinct_vendors: Minimum number of unique root vendors required (default: 2).

    Returns:
        ProviderDiversityResult indicating pass/fail, vendor counts, and explanation.
    """
    if not selections:
        return ProviderDiversityResult(
            is_valid=False,
            distinct_vendor_count=0,
            distinct_vendors=(),
            slots_evaluated=0,
            reason="No model selections provided for diversity evaluation.",
        )

    root_vendors: set[str] = set()
    slots_count = 0

    for item in selections:
        slots_count += 1
        provider_id: str | None = None
        model_name: str | None = None

        if isinstance(item, ModelSelectionSlot):
            provider_id = item.provider_id
            model_name = item.model
        elif isinstance(item, dict):
            provider_id = str(item.get("providerId") or item.get("provider") or "")
            model_name = str(item.get("model") or "")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            provider_id = str(item[0])
            model_name = str(item[1])

        vendor = extract_root_vendor(provider_id, model_name)
        if vendor and vendor != "unknown":
            root_vendors.add(vendor)

    distinct_count = len(root_vendors)
    distinct_tuple = tuple(sorted(root_vendors))

    if distinct_count >= min_distinct_vendors:
        return ProviderDiversityResult(
            is_valid=True,
            distinct_vendor_count=distinct_count,
            distinct_vendors=distinct_tuple,
            slots_evaluated=slots_count,
            reason=f"Satisfies diversity requirement ({distinct_count} vendors: {', '.join(distinct_tuple)} >= {min_distinct_vendors}).",
        )

    return ProviderDiversityResult(
        is_valid=False,
        distinct_vendor_count=distinct_count,
        distinct_vendors=distinct_tuple,
        slots_evaluated=slots_count,
        reason=(
            f"Insufficient provider diversity: found {distinct_count} root vendor(s) "
            f"({', '.join(distinct_tuple) if distinct_tuple else 'none'}), "
            f"at least {min_distinct_vendors} distinct vendors required to avoid single-vendor bias."
        ),
    )
