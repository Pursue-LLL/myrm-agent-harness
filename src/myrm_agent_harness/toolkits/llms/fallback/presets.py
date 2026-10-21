"""Preset fallback strategies for common scenarios.

[INPUT]
- .managed_llm.FallbackModel (POS: Fallback model configuration)
- .config.ProbeConfig (POS: Probe and cooldown configuration)

[OUTPUT]
- FallbackStrategy: Preset strategy configuration
- PRESET_STRATEGIES: Pre-defined strategy mapping
- create_managed_llm_from_preset: Factory function

[POS]
Preset fallback strategies for common use cases. Provides best-practice
configurations out-of-the-box, lowering configuration barrier for new users.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel

from .config import ProbeConfig
from .managed_llm import FallbackModel, ManagedLLM
from .scenario import ScenarioType


@dataclass
class FallbackStrategy:
    """Preset fallback strategy configuration.

    Attributes:
        name: Strategy name
        description: Human-readable description
        main_model: Main model identifier pattern
        fallback_models: List of fallback model configurations
        scenario: Recommended scenario type
        probe_config: Probe and cooldown configuration
    """

    name: str
    description: str
    main_model: str
    fallback_models: list[dict[str, Any]]
    scenario: ScenarioType
    probe_config: ProbeConfig


# Preset strategies for common scenarios
PRESET_STRATEGIES: dict[str, FallbackStrategy] = {
    "gpt-4-standard": FallbackStrategy(
        name="gpt-4-standard",
        description="GPT-4 with quality-cost balanced fallback chain",
        main_model="gpt-4",
        fallback_models=[
            {"name": "gpt-4-turbo", "cost": 0.6, "latency": 0.6, "quality": 0.85},
            {"name": "gpt-4o-mini", "cost": 0.1, "latency": 0.4, "quality": 0.65},
        ],
        scenario=ScenarioType.BALANCED,
        probe_config=ProbeConfig(cooldown_ms=30_000),
    ),
    "gpt-4-high-availability": FallbackStrategy(
        name="gpt-4-high-availability",
        description="GPT-4 with aggressive recovery for critical business",
        main_model="gpt-4",
        fallback_models=[
            {"name": "gpt-4-turbo", "cost": 0.6, "latency": 0.6, "quality": 0.85},
            {"name": "claude-3-opus", "cost": 0.7, "latency": 0.5, "quality": 0.9},
            {"name": "gpt-4o-mini", "cost": 0.1, "latency": 0.4, "quality": 0.65},
        ],
        scenario=ScenarioType.QUALITY_FIRST,
        probe_config=ProbeConfig(cooldown_ms=15_000, probe_interval_ms=10_000, max_probe_attempts=5),
    ),
    "claude-opus-standard": FallbackStrategy(
        name="claude-opus-standard",
        description="Claude 3 Opus with balanced fallback chain",
        main_model="claude-3-opus",
        fallback_models=[
            {"name": "claude-3-sonnet", "cost": 0.4, "latency": 0.4, "quality": 0.8},
            {"name": "claude-3-haiku", "cost": 0.1, "latency": 0.3, "quality": 0.7},
        ],
        scenario=ScenarioType.BALANCED,
        probe_config=ProbeConfig(cooldown_ms=30_000),
    ),
    "gemini-pro-standard": FallbackStrategy(
        name="gemini-pro-standard",
        description="Gemini 1.5 Pro with cross-provider fallback",
        main_model="gemini-1.5-pro",
        fallback_models=[
            {"name": "gpt-4-turbo", "cost": 0.6, "latency": 0.6, "quality": 0.85},
            {"name": "claude-3-opus", "cost": 0.7, "latency": 0.5, "quality": 0.9},
        ],
        scenario=ScenarioType.QUALITY_FIRST,
        probe_config=ProbeConfig(cooldown_ms=30_000),
    ),
    "cost-optimized": FallbackStrategy(
        name="cost-optimized",
        description="Cost-optimized chain starting with efficient models",
        main_model="gpt-4o-mini",
        fallback_models=[
            {"name": "claude-3-haiku", "cost": 0.1, "latency": 0.3, "quality": 0.7},
            {"name": "gemini-1.5-flash", "cost": 0.08, "latency": 0.25, "quality": 0.65},
        ],
        scenario=ScenarioType.REALTIME,
        probe_config=ProbeConfig(cooldown_ms=15_000),
    ),
    "realtime-optimized": FallbackStrategy(
        name="realtime-optimized",
        description="Latency-optimized chain for real-time applications",
        main_model="gpt-4o",
        fallback_models=[
            {"name": "claude-3-haiku", "cost": 0.1, "latency": 0.3, "quality": 0.7},
            {"name": "gpt-4o-mini", "cost": 0.1, "latency": 0.4, "quality": 0.65},
        ],
        scenario=ScenarioType.REALTIME,
        probe_config=ProbeConfig(cooldown_ms=15_000, probe_interval_ms=10_000),
    ),
}


def get_preset_strategy(strategy_name: str) -> FallbackStrategy:
    """Get a preset fallback strategy.

    Args:
        strategy_name: Name of the preset strategy

    Returns:
        FallbackStrategy instance

    Raises:
        ValueError: If strategy_name is not recognized
    """
    if strategy_name not in PRESET_STRATEGIES:
        available = ", ".join(PRESET_STRATEGIES.keys())
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available: {available}")

    return PRESET_STRATEGIES[strategy_name]


def create_managed_llm_from_preset(
    strategy_name: str,
    llm_factory: dict[str, BaseChatModel],
    on_failover: Any = None,
    on_recovery: Any = None,
) -> ManagedLLM:
    """Create ManagedLLM from preset strategy.

    Args:
        strategy_name: Name of the preset strategy
        llm_factory: Dict mapping model names to LLM instances
        on_failover: Optional failover callback
        on_recovery: Optional recovery callback

    Returns:
        Configured ManagedLLM instance

    Raises:
        ValueError: If strategy not found or required models missing from factory

    Example:
        llm_factory = {
            "gpt-4": ChatOpenAI(model="gpt-4"),
            "gpt-4-turbo": ChatOpenAI(model="gpt-4-turbo"),
            "gpt-4o-mini": ChatOpenAI(model="gpt-4o-mini"),
        }

        managed_llm = create_managed_llm_from_preset(
            "gpt-4-standard",
            llm_factory,
        )
    """
    strategy = get_preset_strategy(strategy_name)

    # Validate all required models are available
    required_models = [strategy.main_model] + [fb["name"] for fb in strategy.fallback_models]
    missing_models = [m for m in required_models if m not in llm_factory]
    if missing_models:
        raise ValueError(f"Missing LLM instances for models: {missing_models}. Available: {list(llm_factory.keys())}")

    # Get main LLM
    main_llm = llm_factory[strategy.main_model]

    # Create fallback models
    fallback_models = [
        FallbackModel(
            llm=llm_factory[fb["name"]],
            name=fb["name"],
            cost=fb["cost"],
            latency=fb["latency"],
            quality=fb["quality"],
        )
        for fb in strategy.fallback_models
    ]

    # Create ManagedLLM
    return ManagedLLM(
        main_llm=main_llm,
        fallback_models=fallback_models,
        main_model_name=strategy.main_model,
        scenario=strategy.scenario,
        probe_config=strategy.probe_config,
        on_failover=on_failover,
        on_recovery=on_recovery,
    )
