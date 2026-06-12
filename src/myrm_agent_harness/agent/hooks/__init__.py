"""Agent Hook system — user-configurable lifecycle hooks.

[OUTPUT]
- HookEvent, HookDefinition (4 types), HookResult, AggregatedHookResult
- HookRegistry, HookExecutor
- fire_hook, get_hook_executor, set_hook_executor, payload_from_dataclass
- HookReloader
- Payload dataclasses (PreToolUsePayload, PostToolUsePayload, ...)

[POS]
User-configurable lifecycle hook system. Complements middlewares (framework-internal safety logic) by providing external extension points without source code modification.

"""

from myrm_agent_harness.agent.hooks.executor import (
    HookExecutor,
    HookRegistry,
    bootstrap_hook_registry,
    fire_hook,
    get_hook_executor,
    payload_from_dataclass,
    set_hook_executor,
)
from myrm_agent_harness.agent.hooks.hot_reload import HookReloader
from myrm_agent_harness.agent.hooks.output_spiller import (
    HOOK_OUTPUT_TOKEN_LIMIT,
    HookOutputSpiller,
    spill_hook_contexts,
)
from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md
from myrm_agent_harness.agent.hooks.types import (
    EMPTY_RESULT,
    AggregatedHookResult,
    ApprovalCorrectionPayload,
    CallableHookDefinition,
    CommandHookDefinition,
    HookCallable,
    HookDefinition,
    HookEvent,
    HookResult,
    HttpHookDefinition,
    LLMHookDefinition,
    MemoryArchivedPayload,
    PostToolUseFailurePayload,
    PostToolUsePayload,
    PreCompactPayload,
    PreToolUsePayload,
    SessionEndPayload,
    SessionStartPayload,
    SubagentMergeConflictPayload,
    SubagentStartPayload,
    SubagentStopPayload,
)

__all__ = [
    "EMPTY_RESULT",
    "HOOK_OUTPUT_TOKEN_LIMIT",
    "AggregatedHookResult",
    "ApprovalCorrectionPayload",
    "CallableHookDefinition",
    "CommandHookDefinition",
    "HookCallable",
    "HookDefinition",
    "HookEvent",
    "HookExecutor",
    "HookOutputSpiller",
    "HookRegistry",
    "HookReloader",
    "HookResult",
    "HttpHookDefinition",
    "LLMHookDefinition",
    "MemoryArchivedPayload",
    "PostToolUseFailurePayload",
    "PostToolUsePayload",
    "PreCompactPayload",
    "PreToolUsePayload",
    "SessionEndPayload",
    "SessionStartPayload",
    "SubagentMergeConflictPayload",
    "SubagentStartPayload",
    "SubagentStopPayload",
    "bootstrap_hook_registry",
    "fire_hook",
    "get_hook_executor",
    "parse_hooks_from_skill_md",
    "payload_from_dataclass",
    "set_hook_executor",
    "spill_hook_contexts",
]
