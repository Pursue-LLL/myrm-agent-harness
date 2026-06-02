"""Workspace rules injection middleware.

Injects workspace-level rule files (AGENTS.md, CLAUDE.md, .cursorrules,
.myrm.md, .hermes.md, HERMES.md, .windsurfrules, .myrm/rules/*.md,
.cursor/rules/*.mdc, .claude/CLAUDE.md, .github/copilot-instructions.md)
as a SystemMessage into the prompt on first LLM call.

Injection position: after user_instructions, before memory_context.
This preserves the KV Cache prefix hierarchy:

    [0] System Prompt                    ← cross-user cache ✅
    [1] <user_instructions>              ← per-user stable ✅
    [2] <workspace_context> (this)       ← per-workspace stable ✅
    [3] <user_memory_context>            ← per-user stable ✅
    [4+] Messages                        ← per-turn

⚠️ Self-update reminder: if this file changes, update:
1. agent/context_management/PROMPT_CACHE_PRACTICE.md §2

[INPUT]
- agent.workspace_rules.scanner::scan_workspace_rules, RuleFile
- agent.middlewares._session_context::get_workspace_root

[OUTPUT]
- workspace_rules_middleware: singleton middleware instance

[POS]
Workspace rules injection middleware. Scans workspace for project-level
rule files and injects them as a stable SystemMessage prefix (after
user_instructions, before memory_context) for KV Cache optimization.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)

WORKSPACE_CONTEXT_MARKER = "<workspace_context"


def _has_workspace_context(messages: Sequence[object]) -> bool:
    """Detect whether workspace context has already been injected."""
    for msg in messages[:8]:
        if isinstance(msg, SystemMessage):
            content = msg.content
            if isinstance(content, str) and WORKSPACE_CONTEXT_MARKER in content:
                return True
    return False


def _find_workspace_insert_idx(messages: Sequence[object]) -> int:
    """Find insertion point: after all leading SystemMessages.

    This places workspace_context after system_prompt and user_instructions
    but before HumanMessage/memory learned advisory.
    """
    idx = 0
    for i, msg in enumerate(messages):
        if isinstance(msg, SystemMessage):
            idx = i + 1
        else:
            break
    return idx


def _format_rules_content(rules: Sequence[object]) -> str:
    """Format loaded rule files into a single SystemMessage content."""
    import os

    from myrm_agent_harness.agent.workspace_rules.scanner import RuleFile

    sections: list[str] = []
    for rule in rules:
        if not isinstance(rule, RuleFile):
            continue
        filename = os.path.basename(rule.path)
        sections.append(f"### {filename}\n{rule.content}")

    body = "\n\n".join(sections)
    return (
        '<workspace_context source="project_rules">\n'
        "[Project-level rules discovered in workspace. "
        "Follow these instructions for project-specific behavior.]\n\n"
        f"{body}\n"
        "</workspace_context>"
    )


class WorkspaceRulesMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Workspace rules injection middleware.

    On the first LLM call, scans the workspace for project-level rule
    files and injects them as a SystemMessage. Subsequent calls detect
    the marker and skip injection.
    """

    name = "workspace_rules_middleware"

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        raise NotImplementedError(
            "WorkspaceRulesMiddleware does not support synchronous wrap_model_call"
        )

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state
        raw_state_messages = state.get("messages", [])
        state_messages: list[object] = (
            list(raw_state_messages) if isinstance(raw_state_messages, list) else []
        )

        already_injected = _has_workspace_context(
            state_messages
        ) or _has_workspace_context(request.messages)

        if already_injected:
            return await handler(request)

        workspace_root = self._resolve_workspace_root(request)
        if not workspace_root:
            return await handler(request)

        from myrm_agent_harness.agent.workspace_rules.scanner import (
            scan_workspace_rules,
        )

        rules = scan_workspace_rules(workspace_root)
        if not rules:
            return await handler(request)

        content = _format_rules_content(rules)
        rules_msg = SystemMessage(content=content)

        new_messages = list(request.messages)
        insert_idx = _find_workspace_insert_idx(new_messages)
        new_messages.insert(insert_idx, rules_msg)

        request = request.override(messages=new_messages)

        logger.info(
            "Injected workspace rules (%d files, %d chars) at position %d",
            len(rules),
            len(content),
            insert_idx,
        )

        return await handler(request)

    @staticmethod
    def _resolve_workspace_root(request: ModelRequest) -> str:
        """Extract workspace_root from request context or session context."""
        if request.runtime is not None:
            context = getattr(request.runtime, "context", None)
            if isinstance(context, dict):
                raw = context.get("workspace_path")
                if isinstance(raw, str) and raw:
                    return raw

        from myrm_agent_harness.agent.middlewares._session_context import (
            get_workspace_root,
        )

        return get_workspace_root()


workspace_rules_middleware = WorkspaceRulesMiddleware()
