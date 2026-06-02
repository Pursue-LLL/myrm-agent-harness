from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    "DEFAULT_JUDGE_SYSTEM_PROMPT",
    "DEFAULT_REASONING_KEYWORDS",
    "DEFAULT_SIMPLE_INDICATORS",
    "DEFAULT_STANDARD_KEYWORDS",
    "PenaltyTracker",
    "PrivacyRoutingModel",
    "RoutingResult",
    "RoutingTier",
    "get_penalty_tracker",
    "record_misroute",
    "route_task",
]

_CR = "myrm_agent_harness.toolkits.llms.routing.complexity_router"

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
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        from importlib import import_module

        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
