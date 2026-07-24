from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .combo import (
        ComboConfig,
        ComboResolver,
        ComboTarget,
        ResolvedTarget,
        RoutingStrategy,
        StrategyContext,
        apply_strategy,
    )
    from .complexity_router import (
        DEFAULT_JUDGE_SYSTEM_PROMPT,
        DEFAULT_REASONING_KEYWORDS,
        DEFAULT_SIMPLE_INDICATORS,
        DEFAULT_STANDARD_KEYWORDS,
        PenaltyTracker,
        RoutingResult,
        RoutingTier,
        get_penalty_tracker,
        record_misroute,
        route_task,
    )
    from .privacy_routing import PrivacyRoutingModel

__all__ = [
    "ComboConfig",
    "ComboResolver",
    "ComboTarget",
    "DEFAULT_JUDGE_SYSTEM_PROMPT",
    "DEFAULT_REASONING_KEYWORDS",
    "DEFAULT_SIMPLE_INDICATORS",
    "DEFAULT_STANDARD_KEYWORDS",
    "PenaltyTracker",
    "PrivacyRoutingModel",
    "ResolvedTarget",
    "RoutingResult",
    "RoutingStrategy",
    "RoutingTier",
    "StrategyContext",
    "apply_strategy",
    "get_penalty_tracker",
    "record_misroute",
    "route_task",
]

_CR = "myrm_agent_harness.toolkits.llms.routing.complexity_router"
_COMBO = "myrm_agent_harness.toolkits.llms.routing.combo"

_LAZY_IMPORTS = {
    "PrivacyRoutingModel": ("myrm_agent_harness.toolkits.llms.routing.privacy_routing", "PrivacyRoutingModel"),
    "RoutingTier": (_CR, "RoutingTier"),
    "RoutingResult": (_CR, "RoutingResult"),
    "route_task": (_CR, "route_task"),
    "DEFAULT_STANDARD_KEYWORDS": (_CR, "DEFAULT_STANDARD_KEYWORDS"),
    "DEFAULT_REASONING_KEYWORDS": (_CR, "DEFAULT_REASONING_KEYWORDS"),
    "DEFAULT_SIMPLE_INDICATORS": (_CR, "DEFAULT_SIMPLE_INDICATORS"),
    "DEFAULT_JUDGE_SYSTEM_PROMPT": (_CR, "DEFAULT_JUDGE_SYSTEM_PROMPT"),
    "PenaltyTracker": (_CR, "PenaltyTracker"),
    "record_misroute": (_CR, "record_misroute"),
    "get_penalty_tracker": (_CR, "get_penalty_tracker"),
    "ComboConfig": (_COMBO, "ComboConfig"),
    "ComboTarget": (_COMBO, "ComboTarget"),
    "RoutingStrategy": (_COMBO, "RoutingStrategy"),
    "ComboResolver": (_COMBO, "ComboResolver"),
    "ResolvedTarget": (_COMBO, "ResolvedTarget"),
    "StrategyContext": (_COMBO, "StrategyContext"),
    "apply_strategy": (_COMBO, "apply_strategy"),
}


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in _LAZY_IMPORTS:
        from importlib import import_module

        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
