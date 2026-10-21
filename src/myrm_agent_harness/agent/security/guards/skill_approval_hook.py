"""Skill Approval Hook — skill-level before_tool_call authorization.

Allows loaded skills to participate in tool-call security decisions
via an optional ``before_tool_call`` hook. Skills can:
- allow: let the call proceed
- block: reject the call immediately (highest priority)
- require_approval: forward to the HITL approval flow

Conflict resolution follows deny-wins semantics: any block from any
skill rejects the call; any require_approval triggers HITL; all must
allow for the call to proceed without approval.

[INPUT]
- (none — self-contained, pure standard library + uuid)

[OUTPUT]
- ToolCallDecision: allow / block / require_approval
- SkillApprovalHook: Protocol for skills implementing the hook
- evaluate_skill_hooks(): run all loaded skill hooks and merge verdicts
- SkillHookVerdict: merged result from all skill hooks

[POS]
Integrated into tool_interceptor_middleware between the onion policy
engine (L1-L3) and HITL approval. When a skill returns require_approval,
the request is forwarded to the existing HITL approval flow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class HookAction(StrEnum):
    """Decision action from a skill hook."""

    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class ToolCallDecision:
    """A single skill's decision on a tool call."""

    action: HookAction
    reason: str = ""
    title: str = ""
    description: str = ""
    timeout_behavior: str = "deny"  # "allow" or "deny"


_DECISION_ALLOW = ToolCallDecision(action=HookAction.ALLOW)


@runtime_checkable
class SkillApprovalHook(Protocol):
    """Protocol for skills that want to participate in tool-call authorization.

    Skills implement this as an optional method. If not implemented,
    the skill is treated as allowing all tool calls.
    """

    def before_tool_call(self, tool_name: str, tool_args: dict[str, object]) -> ToolCallDecision: ...


@dataclass(frozen=True, slots=True)
class SkillHookVerdict:
    """Merged result from evaluating all skill hooks.

    Fields:
        action: the final merged action (allow/block/require_approval)
        reason: explanation of the decision
        approval_id: server-generated UUID for require_approval (anti-forgery)
        title: approval request title (from skill)
        description: approval request description (from skill)
        timeout_behavior: what to do on approval timeout ("allow" or "deny")
        blocking_skill: name of the skill that blocked (if any)
    """

    action: HookAction
    reason: str
    approval_id: str = ""
    title: str = ""
    description: str = ""
    timeout_behavior: str = "deny"
    blocking_skill: str = ""


_VERDICT_ALLOW = SkillHookVerdict(action=HookAction.ALLOW, reason="")


def evaluate_skill_hooks(
    hooks: list[tuple[str, SkillApprovalHook]], tool_name: str, tool_args: dict[str, object]
) -> SkillHookVerdict:
    """Evaluate all loaded skill hooks for a tool call.

    Conflict resolution (deny-wins):
    1. Any block → immediate reject (first block wins)
    2. Any require_approval → forward to HITL (merged)
    3. All allow → proceed

    Args:
        hooks: list of (skill_name, hook_instance) pairs
        tool_name: the tool being called
        tool_args: the tool arguments

    Returns:
        SkillHookVerdict with the merged decision
    """
    if not hooks:
        return _VERDICT_ALLOW

    approval_requests: list[tuple[str, ToolCallDecision]] = []

    for skill_name, hook in hooks:
        try:
            decision = hook.before_tool_call(tool_name, tool_args)
        except Exception as exc:
            return SkillHookVerdict(
                action=HookAction.BLOCK,
                reason=f"Skill '{skill_name}' hook raised an exception: {exc}",
                blocking_skill=skill_name,
            )

        if decision.action == HookAction.BLOCK:
            return SkillHookVerdict(
                action=HookAction.BLOCK,
                reason=decision.reason or f"Blocked by skill '{skill_name}'",
                blocking_skill=skill_name,
            )

        if decision.action == HookAction.REQUIRE_APPROVAL:
            approval_requests.append((skill_name, decision))

    if approval_requests:
        skill_name, first_request = approval_requests[0]
        reasons = [f"{name}: {d.reason}" for name, d in approval_requests]
        return SkillHookVerdict(
            action=HookAction.REQUIRE_APPROVAL,
            reason="; ".join(reasons),
            approval_id=f"skill:{uuid.uuid4().hex[:12]}",
            title=first_request.title or f"Approval required by skill '{skill_name}'",
            description=first_request.description,
            timeout_behavior=first_request.timeout_behavior,
        )

    return _VERDICT_ALLOW
