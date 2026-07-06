"""Orchestration control plane — signals and runtime hooks (not Action Tools).

[OUTPUT]
- signals: JSON schema contracts intercepted by orchestrators (DR, Verifier)
- hooks: middleware-injected pseudo tool_calls (CompletionGuard)

[POS]
Separates control-plane LLM signals from Action Tools in ``tool_management/``.
Action Tools live in ``ToolRegistry`` + ``_TOOL_LAYERS``; orchestration signals do not.
"""

from .hooks import RUNTIME_HOOK_NAMES, is_runtime_hook
from .signals.catalog import ORCHESTRATION_SIGNAL_NAMES

__all__ = [
    "ORCHESTRATION_SIGNAL_NAMES",
    "RUNTIME_HOOK_NAMES",
    "is_runtime_hook",
]
