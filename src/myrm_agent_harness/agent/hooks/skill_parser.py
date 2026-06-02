"""SKILL.md Hook parser — extract hooks from Markdown frontmatter.

Parses hook definitions and allowed-tools from skill YAML frontmatter,
producing new-style HookDefinition objects that can be registered with HookRegistry.

[INPUT]
- (none)

[OUTPUT]
- parse_hooks_from_skill_md: Parse hooks and allowed-tools from SKILL.md frontmatter.

[POS]
SKILL.md Hook parser — extract hooks from Markdown frontmatter.
"""

from __future__ import annotations

import logging
import os
import re

import yaml

from myrm_agent_harness.agent.hooks.types import CommandHookDefinition, HookDefinition, HookEvent, HttpHookDefinition

logger = logging.getLogger(__name__)

_HOOK_EVENT_MAP: dict[str, HookEvent] = {
    "SessionStart": HookEvent.SESSION_START,
    "SessionEnd": HookEvent.SESSION_END,
    "BeforeToolUse": HookEvent.PRE_TOOL_USE,
    "PreToolUse": HookEvent.PRE_TOOL_USE,
    "AfterToolUse": HookEvent.POST_TOOL_USE,
    "PostToolUse": HookEvent.POST_TOOL_USE,
    "PostToolUseFailure": HookEvent.POST_TOOL_USE_FAILURE,
    "PreCompact": HookEvent.PRE_COMPACT,
    "Stop": HookEvent.SESSION_END,
}


def parse_hooks_from_skill_md(skill_content: str) -> tuple[list[tuple[HookEvent, HookDefinition]], list[str] | None]:
    """Parse hooks and allowed-tools from SKILL.md frontmatter.

    Returns:
        (hooks, allowed_tools) — hooks is list of (event, definition) pairs
    """
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill_content, re.DOTALL)
    if not frontmatter_match:
        return [], None

    try:
        metadata = yaml.safe_load(frontmatter_match.group(1))
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML frontmatter: %s", e)
        return [], None

    if not isinstance(metadata, dict):
        return [], None

    hooks = _parse_hooks(metadata.get("hooks", {}))
    allowed_tools = _parse_allowed_tools(metadata.get("allowed-tools"))

    return hooks, allowed_tools


def _parse_hooks(hooks_data: object) -> list[tuple[HookEvent, HookDefinition]]:
    if not isinstance(hooks_data, dict):
        return []

    hooks: list[tuple[HookEvent, HookDefinition]] = []

    for hook_type_str, hook_configs in hooks_data.items():
        event = _HOOK_EVENT_MAP.get(str(hook_type_str))
        if event is None:
            logger.warning("Unknown hook type: %s", hook_type_str)
            continue

        if not isinstance(hook_configs, list):
            continue

        for config in hook_configs:
            if not isinstance(config, dict):
                continue

            script = config.get("script", "")
            url = config.get("url", "")

            if not script and not url:
                logger.warning("Hook missing script or url: %s", config.get("description", "?"))
                continue

            if script and url:
                script = ""

            tool_matcher = _build_matcher(config.get("tools"))

            if url:
                hooks.append(
                    (
                        event,
                        HttpHookDefinition(
                            url=url,
                            headers=_build_auth_headers(config.get("auth", "")),
                            matcher=tool_matcher,
                            block_on_failure=config.get("failure_mode", "").lower() in ("fail_closed", "closed"),
                            timeout_seconds=float(config.get("timeout", 10)),
                        ),
                    )
                )
            else:
                hooks.append(
                    (
                        event,
                        CommandHookDefinition(
                            command=script,
                            matcher=tool_matcher,
                            block_on_failure=config.get("failure_mode", "").lower() in ("fail_closed", "closed"),
                            timeout_seconds=float(config.get("timeout", 10)),
                        ),
                    )
                )

    return hooks


def _build_matcher(tools: list[str] | str | None) -> str:
    """Convert tool names list to a fnmatch-style matcher pattern."""
    if not tools:
        return ""
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]
    if len(tools) == 1:
        return tools[0]
    return ""


def _build_auth_headers(auth_raw: object) -> dict[str, str]:
    if not auth_raw:
        return {}
    value = _resolve_auth(str(auth_raw).strip())
    if value:
        return {"Authorization": value}
    return {}


_ENV_VAR_PATTERN = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")


def _resolve_auth(raw: str) -> str:
    match = _ENV_VAR_PATTERN.match(raw)
    if match:
        env_val = os.environ.get(match.group(1), "")
        if not env_val:
            logger.warning("Hook auth env var '%s' not set", match.group(1))
        return env_val
    return raw


def _parse_allowed_tools(raw: object) -> list[str] | None:
    if not raw:
        return None
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if t]
    return None
