"""SKILL.md Hook parser — extract hooks from Markdown frontmatter.

Parses hook definitions and allowed-tools from skill YAML frontmatter,
producing new-style HookDefinition objects that can be registered with HookRegistry.

[INPUT]
- hooks.types::CommandHookDefinition, HttpHookDefinition, HookEvent (POS: Hook type definitions)

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

from myrm_agent_harness.agent.hooks.types import (
    CommandHookDefinition,
    HookDefinition,
    HookEvent,
    HookSource,
    HttpHookDefinition,
)

logger = logging.getLogger(__name__)

_HOOK_EVENT_MAP: dict[str, HookEvent] = {
    "SessionStart": HookEvent.SESSION_START,
    "SessionEnd": HookEvent.SESSION_END,
    "BeforeToolUse": HookEvent.PRE_TOOL_USE,
    "PreToolUse": HookEvent.PRE_TOOL_USE,
    "AfterToolUse": HookEvent.POST_TOOL_USE,
    "PostToolUse": HookEvent.POST_TOOL_USE,
    "PostToolUseFailure": HookEvent.POST_TOOL_USE_FAILURE,
    "Stop": HookEvent.SESSION_END,
}

_DEFAULT_TIMEOUT_SECONDS = 10
_FAIL_CLOSED_MODES = frozenset({"fail_closed", "closed"})
_FAIL_OPEN_MODES = frozenset({"", "fail_open", "open"})


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
            try:
                hook = _build_hook(config)
            except (TypeError, ValueError) as exc:
                # One malformed entry must neither discard its siblings nor fail skill loading.
                logger.warning("Skipping invalid %s hook (%s): %s", hook_type_str, config.get("description", "?"), exc)
                continue
            if hook is not None:
                hooks.append((event, hook))

    return hooks


def _build_hook(config: dict[object, object]) -> HookDefinition | None:
    """Build one hook from a frontmatter entry; ``None`` when it declares no action."""
    script = _optional_text(config.get("script"), "script")
    url = _optional_text(config.get("url"), "url")

    if not script and not url:
        logger.warning("Hook missing script or url: %s", config.get("description", "?"))
        return None
    if script and url:
        logger.warning("Hook declares both script and url, using url: %s", config.get("description", "?"))

    matcher = _build_matcher(config.get("tools"))
    block_on_failure = _blocks_on_failure(config.get("failure_mode"))
    timeout_seconds = _timeout_seconds(config.get("timeout"))

    if url:
        raw_secret = config.get("secret")
        secret = _resolve_env_or_literal(raw_secret) if raw_secret else None
        return HttpHookDefinition(
            url=url,
            headers=_build_auth_headers(config.get("auth", "")),
            matcher=matcher,
            block_on_failure=block_on_failure,
            timeout_seconds=timeout_seconds,
            secret=secret or None,
            fire_and_forget=bool(config.get("fire_and_forget", False)),
            source=HookSource.SKILL,
        )
    return CommandHookDefinition(
        command=script,
        matcher=matcher,
        block_on_failure=block_on_failure,
        timeout_seconds=timeout_seconds,
        source=HookSource.SKILL,
    )


def _optional_text(value: object, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"'{field}' must be a string, got {type(value).__name__}")
    return value if value.strip() else ""


def _timeout_seconds(raw: object) -> int:
    if raw is None:
        return _DEFAULT_TIMEOUT_SECONDS
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise TypeError(f"'timeout' must be a number of seconds, got {raw!r}")
    return round(raw)


def _blocks_on_failure(raw: object) -> bool:
    """Whether the hook opts into ``fail_closed``; unknown spellings are reported, never silent."""
    if raw is None:
        return False
    mode = str(raw).strip().lower().replace("-", "_")
    if mode in _FAIL_CLOSED_MODES:
        return True
    if mode not in _FAIL_OPEN_MODES:
        logger.warning("Unknown failure_mode %r treated as fail_open (use fail_closed to block on failure)", raw)
    return False


def _build_matcher(tools: object) -> str:
    """Join tool-name patterns into one matcher; ``|`` separates alternatives, empty means every tool."""
    if tools is None:
        return ""
    if isinstance(tools, str):
        names = tools.split(",")
    elif isinstance(tools, list):
        names = [name for name in tools if isinstance(name, str)]
        if len(names) != len(tools):
            raise TypeError("'tools' entries must be strings")
    else:
        raise TypeError("'tools' must be a tool name or a list of tool names")
    return "|".join(name.strip() for name in names if name.strip())


def _build_auth_headers(auth_raw: object) -> dict[str, str]:
    if not auth_raw:
        return {}
    value = _resolve_auth(str(auth_raw).strip())
    if value:
        return {"Authorization": value}
    return {}


_ENV_VAR_PATTERN = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")


def _resolve_auth(raw: str) -> str:
    return _resolve_env_or_literal(raw, warn_missing=True)


def _resolve_env_or_literal(raw: object, *, warn_missing: bool = False) -> str:
    """Resolve ``$VAR`` / ``${VAR}`` to env value, or return literal string."""
    text = str(raw).strip()
    if not text:
        return ""
    match = _ENV_VAR_PATTERN.match(text)
    if match:
        env_val = os.environ.get(match.group(1), "")
        if not env_val and warn_missing:
            logger.warning("Hook env var '%s' not set", match.group(1))
        return env_val
    return text


def _parse_allowed_tools(raw: object) -> list[str] | None:
    if not raw:
        return None
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if t]
    return None
