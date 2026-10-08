"""`[use <reference>]` finds the skill a user means, whatever name the backend lists it under.

The slash palette sends the catalog name (``audit-probe``). A product backend may list the same skill
under a runtime name (``audit_probe_skill``) with a storage id that is neither (``local::...``); the SOP
preload and the skill hooks must still reach it, and must never guess between two skills.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.hooks import get_hook_executor, set_hook_executor
from myrm_agent_harness.agent.hooks.types import CommandHookDefinition, HookEvent
from myrm_agent_harness.agent.skill_agent import SkillAgent, wait_all_background_tasks
from myrm_agent_harness.agent.skill_agent.skill_reference import resolve_skill_reference
from myrm_agent_harness.backends.skills.types import SkillMetadata


def _meta(name: str, storage_skill_id: str | None = None) -> SkillMetadata:
    return SkillMetadata(name=name, description=f"{name} skill", storage_skill_id=storage_skill_id)


class TestResolveSkillReference:
    def test_exact_name_wins_over_a_canonical_twin(self) -> None:
        skills = [_meta("pdf_generator_skill"), _meta("pdf-generator")]

        assert resolve_skill_reference("pdf-generator", skills) is skills[1]

    def test_storage_id_resolves(self) -> None:
        skills = [_meta("audit_probe_skill", "local::0123456789abcdef")]

        assert resolve_skill_reference("local::0123456789abcdef", skills) is skills[0]

    @pytest.mark.parametrize(
        "reference",
        ["audit-probe", "Audit-Probe", "audit_probe", "audit_probe_skill", " audit-probe ", "audit probe"],
    )
    def test_spelling_variants_of_one_skill_resolve(self, reference: str) -> None:
        skills = [_meta("audit_probe_skill"), _meta("other_skill")]

        assert resolve_skill_reference(reference, skills) is skills[0]

    def test_ambiguous_spelling_resolves_to_nothing(self) -> None:
        skills = [_meta("foo-bar"), _meta("foo_bar_skill")]

        assert resolve_skill_reference("foo_bar", skills) is None

    @pytest.mark.parametrize("reference", ["", "   ", "missing", "audit"])
    def test_unknown_or_empty_reference_resolves_to_nothing(self, reference: str) -> None:
        assert resolve_skill_reference(reference, [_meta("audit_probe_skill")]) is None


_AUDIT_SKILL_MD = (
    "---\nname: audit-probe\ndescription: audit probe skill\n"
    "hooks:\n  PreToolUse:\n    - script: 'echo audited'\n      tools: [bash_*]\n---\n# audit-probe\n\nDo the thing.\n"
)
_STORAGE_ID = "local::0123456789abcdef"


class _ServerShapedBackend:
    """Lists skills under a runtime name and serves SKILL.md by that name or by storage id."""

    def __init__(self, listed: list[SkillMetadata], content_by_key: dict[str, str]) -> None:
        self._listed = listed
        self._content_by_key = content_by_key

    async def list_skills(self) -> list[SkillMetadata]:
        return list(self._listed)

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        return [s for s in self._listed if s.name in skill_ids or s.storage_skill_id in skill_ids]

    async def get_skill_content(self, skill_name: str) -> str:
        try:
            return self._content_by_key[skill_name]
        except KeyError:
            raise FileNotFoundError(skill_name) from None

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        raise FileNotFoundError(path)

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        return []


def _agent(*listed: SkillMetadata) -> SkillAgent:
    content = {key: _AUDIT_SKILL_MD for skill in listed for key in (skill.name, skill.storage_skill_id) if key}
    return SkillAgent(llm=AsyncMock(), skill_backend=_ServerShapedBackend(list(listed), content))


@pytest.fixture(autouse=True)
def fresh_hook_session() -> Iterator[None]:
    previous = get_hook_executor()
    set_hook_executor(None)
    yield
    set_hook_executor(previous)


@pytest.fixture
def streamed_hooks(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []

    async def fake_run(self: BaseAgent, query: object, **_: object) -> AsyncGenerator[dict[str, object]]:
        executor = get_hook_executor()
        assert executor is not None
        seen.append(
            [h.command for h in executor.registry.get(HookEvent.PRE_TOOL_USE) if isinstance(h, CommandHookDefinition)]
        )
        yield {"type": "message", "data": "done"}

    monkeypatch.setattr(BaseAgent, "run", fake_run)
    return seen


@pytest.mark.asyncio
async def test_catalog_name_activates_the_hooks_of_a_runtime_named_skill(streamed_hooks: list[list[str]]) -> None:
    agent = _agent(_meta("audit_probe_skill", _STORAGE_ID))

    _ = [event async for event in agent.run("[use audit-probe] audit my shell")]
    await wait_all_background_tasks()

    assert streamed_hooks == [["echo audited"]]


@pytest.mark.asyncio
async def test_hitl_resume_finds_the_runtime_named_skill_of_the_interrupted_turn(
    streamed_hooks: list[list[str]],
) -> None:
    agent = _agent(_meta("audit_probe_skill", _STORAGE_ID))
    history = [["human", "[use audit-probe] audit my shell"], ["assistant", "let me run it"]]

    _ = [event async for event in agent.run(Command(resume={"decision": "approve"}), chat_history=history)]
    await wait_all_background_tasks()

    assert streamed_hooks == [["echo audited"]]


@pytest.mark.asyncio
async def test_two_references_to_one_skill_inject_it_once(streamed_hooks: list[list[str]]) -> None:
    agent = _agent(_meta("audit_probe_skill", _STORAGE_ID))

    query, _, preloaded = await agent._preload_explicit_skill("[use audit-probe,audit_probe_skill] go")

    assert [skill.name for skill in preloaded] == ["audit_probe_skill"]
    assert query.count("--- Skill: audit_probe_skill ---") == 1


@pytest.mark.asyncio
async def test_ambiguous_reference_activates_nothing(streamed_hooks: list[list[str]]) -> None:
    agent = _agent(_meta("foo-bar", "id-1"), _meta("foo_bar_skill", "id-2"))

    _ = [event async for event in agent.run("[use foo_bar] audit")]
    await wait_all_background_tasks()

    assert streamed_hooks == [[]]
