"""Real-LLM integration: SKILL.md command hooks through the live SkillAgent chain.

Chain under test, no mocks on the key path:
SKILL.md frontmatter -> ``parse_hooks_from_skill_md`` -> ``SkillMetadata.hooks`` ->
``SkillAgent.run(active_skill=...)`` -> hook registry -> SESSION_START / PRE_TOOL_USE
firing -> ``HookExecutor`` -> command gate -> real subprocess, with a real LLM
choosing the tool call. The only instrumentation is a pass-through spy that
records each command hook's result.

Requires: BASIC_API_KEY / BASIC_BASE_URL / BASIC_MODEL (from .env.test).
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.tools import tool

from myrm_agent_harness.agent.hooks import HookEvent, HookExecutor, HookSource, parse_hooks_from_skill_md
from myrm_agent_harness.agent.hooks.types import CommandHookDefinition, HookResult
from myrm_agent_harness.agent.meta_tools.mount_policy import FileAccessMode
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.types import AgentRuntimeConfig
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.core.security.types import PermissionAction, PermissionRule, SecurityConfig
from tests.integration.llm_extraction.litellm_creds import litellm_config_for

pytestmark = [pytest.mark.integration, pytest.mark.timeout(240)]

_ENV_TEST = Path(__file__).resolve().parents[3] / "myrm-agent" / "myrm-agent-server" / ".env.test"

# Attacker-shaped session id: a client-supplied message id reaches the SESSION_START
# payload. Both substitution forms and a command separator must stay literal data.
_HOSTILE_MESSAGE_ID = "m-$(whoami)-`whoami`;x"
_FINAL_ANSWER = "HOOKS-OK"
# Canonical runtime name (the framework appends ``_tool`` otherwise); hook matchers
# and permission rules are keyed on it.
_TOOL_NAME = "record_note_tool"


@pytest.fixture(autouse=True)
def _load_env_test() -> None:
    """Load .env.test into the process environment (never overriding existing vars)."""
    if not _ENV_TEST.exists():
        pytest.skip(f"{_ENV_TEST} not found — real-LLM integration cannot run")
    for line in _ENV_TEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key and value:
            os.environ.setdefault(key, value)


@pytest.fixture
def basic_llm():
    from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM

    api_key, base_url, model, provider = litellm_config_for("BASIC")
    return ChatLiteLLM(
        model=model,
        api_key=api_key,
        api_base=base_url,
        custom_llm_provider=provider,
        temperature=0.0,
        max_tokens=2048,
    )


@pytest.fixture
def hook_runs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[CommandHookDefinition, HookResult]]:
    """Record every command hook execution while delegating to the real implementation."""
    runs: list[tuple[CommandHookDefinition, HookResult]] = []
    original = HookExecutor._run_command

    async def _spy(
        self: HookExecutor, hook: CommandHookDefinition, event: str, payload: dict[str, object]
    ) -> HookResult:
        result = await original(self, hook, event, payload)
        runs.append((hook, result))
        return result

    monkeypatch.setattr(HookExecutor, "_run_command", _spy)
    return runs


@tool(_TOOL_NAME)
def record_note(note: str) -> str:
    """Record a short note and return a receipt."""
    return f"recorded: {note}"


class _StubSkillBackend:
    """Minimal SkillBackend: serves the probe skill's real SKILL.md text."""

    def __init__(self, skill: SkillMetadata, content: str) -> None:
        self._skill = skill
        self._content = content

    async def list_skills(self) -> list[SkillMetadata]:
        return [self._skill]

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        return [self._skill] if self._skill.name in skill_ids else []

    async def get_skill_content(self, skill_name: str) -> str:
        return self._content

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        return b""


def _skill_md(out: Path) -> str:
    return f"""---
name: hook_probe_skill
description: Probe skill whose command hooks audit the agent run.
hooks:
  SessionStart:
    - script: 'printf "%s" "$ARGUMENTS" > {out}/session_payload.json'
      description: Capture the session payload with the double-quoted placeholder.
    - script: 'echo "session at $(date +%s); event=${{HOOK_EVENT}}" >> {out}/audit.log'
      description: Benign audit using substitution, chaining and a redirect.
    - script: 'eval "echo escalated > {out}/escalated.marker"'
      description: Third-party escalation that the gate must refuse.
  PreToolUse:
    - script: 'printf "%s" $ARGUMENTS > {out}/tool_payload.json'
      tools: {_TOOL_NAME}
      description: Capture the tool call payload with the bare placeholder.
---
# Hook probe

Use the {_TOOL_NAME} tool when asked.
"""


def _security_config(workspace: Path) -> SecurityConfig:
    """Workspace profile plus an explicit allow for the probe tool.

    Tools unknown to the framework resolve to ``mcp_invoke`` (approval required), so a
    per-tool rule is the declarative way to let the probe run without bypassing approval.
    """
    base = SecurityConfig.workspace(allowed_roots=(str(workspace),))
    return replace(base, ruleset=(*base.ruleset, PermissionRule(_TOOL_NAME, "*", PermissionAction.ALLOW)))


@pytest.mark.asyncio
async def test_skill_command_hooks_are_governed_end_to_end(
    basic_llm, hook_runs: list[tuple[CommandHookDefinition, HookResult]], tmp_path: Path
) -> None:
    out = tmp_path / "hook-out"
    out.mkdir()
    content = _skill_md(out)
    hooks, _ = parse_hooks_from_skill_md(content)
    skill = SkillMetadata(name="hook_probe_skill", description="Probe skill", hooks=hooks)
    assert {hook.source for _, hook in hooks} == {HookSource.SKILL}
    assert [event for event, _ in hooks].count(HookEvent.SESSION_START) == 3

    agent = SkillAgent(
        llm=basic_llm,
        skill_backend=_StubSkillBackend(skill, content),
        tools=[record_note],
        enable_memory_auto_extraction=False,
        enable_shell_tools=False,
        file_access_mode=FileAccessMode.NONE,
        config=AgentRuntimeConfig(security_config=_security_config(tmp_path)),
    )
    query = (
        f"Call the {_TOOL_NAME} tool exactly once with note set to 'hook governance probe'. "
        f"Then reply with exactly: {_FINAL_ANSWER}"
    )

    try:
        events = [
            event
            async for event in agent.run(
                query,
                message_id=_HOSTILE_MESSAGE_ID,
                active_skill=skill,
                context={
                    "chat_id": "hook-probe-chat",
                    "session_id": "chat_hook_probe",
                    "workspaces_storage_root": str(tmp_path / "workspaces-root"),
                },
            )
        ]
    finally:
        await agent.close()

    answer = "".join(str(e["data"]) for e in events if e.get("type") == "message" and isinstance(e.get("data"), str))
    ran = {hook.command: result for hook, result in hook_runs}
    print(f"\nQUERY: {query}")
    print(f"STREAM EVENT TYPES: {sorted({str(e.get('type')) for e in events})}")
    print(f"FINAL ANSWER: {answer.strip()[:200]!r}")
    for command, result in ran.items():
        print(f"HOOK success={result.success} gate_blocked={result.metadata.get('gate_blocked', False)} :: {command}")

    # Benign hooks ran: redirects, `;`, `$()`, `${}` are ordinary shell in a skill hook.
    audit_lines = (out / "audit.log").read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    assert audit_lines[0].startswith("session at ") and audit_lines[0].endswith("event=session_start")

    # Hostile event data stays data: the double-quoted placeholder delivers the exact payload.
    session_payload = json.loads((out / "session_payload.json").read_text(encoding="utf-8"))
    assert session_payload["session_id"] == _HOSTILE_MESSAGE_ID

    # The third-party `eval` hook was refused by the gate and never executed.
    assert not (out / "escalated.marker").exists()
    refused = [result for result in ran.values() if result.metadata.get("gate_blocked")]
    assert len(refused) == 1
    assert "eval" in refused[0].reason and refused[0].success is False and refused[0].blocked is False
    assert all(result.success for result in ran.values() if not result.metadata.get("gate_blocked"))

    # The real LLM called the tool, so PRE_TOOL_USE fired and delivered the call payload.
    tool_payload = json.loads((out / "tool_payload.json").read_text(encoding="utf-8"))
    assert tool_payload["tool_name"] == _TOOL_NAME
    assert "note" in tool_payload["tool_input"]

    # The run itself completed normally despite the refused hook.
    assert _FINAL_ANSWER.lower() in answer.lower()
