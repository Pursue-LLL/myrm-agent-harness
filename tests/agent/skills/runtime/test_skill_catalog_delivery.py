"""Tests for bound skill catalog HumanMessage delivery."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool import (
    build_skill_select_static_description,
    create_select_skill_tool,
)
from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
    build_bound_skills_block,
    ensure_skill_catalog_in_messages,
    strip_catalog_blocks,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata


def _skill(name: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"{name} description",
        model_invocable=True,
        available=True,
    )


class _StubSkillBackend:
    async def get_skill_content(self, skill_name: str) -> str:
        return f"# {skill_name}\n"


def test_strip_catalog_blocks_removes_bound_skills_and_updates() -> None:
    raw = (
        '<bound_skills hash="old">\n<skills></skills>\n</bound_skills>\n\n'
        '<bound_skills_update hash="old2">\n<skills></skills>\n</bound_skills_update>\n\n'
        "hello"
    )
    assert strip_catalog_blocks(raw) == "hello"


def test_build_bound_skills_block_contains_skill_name() -> None:
    block = build_bound_skills_block([_skill("alpha_skill")])
    assert block.startswith('<bound_skills hash="')
    assert "alpha_skill" in block
    assert block.endswith("</bound_skills>")


def test_ensure_skill_catalog_injects_on_first_human_message() -> None:
    messages = [
        HumanMessage(content="first user turn"),
        AIMessage(content="assistant"),
        HumanMessage(content="second user turn"),
    ]
    ensure_skill_catalog_in_messages(messages, [_skill("alpha_skill")])

    first = messages[0]
    assert isinstance(first, HumanMessage)
    assert isinstance(first.content, str)
    assert first.content.startswith("<bound_skills")
    assert "alpha_skill" in first.content
    assert "first user turn" in first.content

    second = messages[2]
    assert isinstance(second, HumanMessage)
    assert second.content == "second user turn"


def test_ensure_skill_catalog_is_idempotent_on_reinject() -> None:
    messages = [HumanMessage(content="hello")]
    skills = [_skill("alpha_skill")]
    ensure_skill_catalog_in_messages(messages, skills)
    first_pass = messages[0].content
    ensure_skill_catalog_in_messages(messages, skills)
    second_pass = messages[0].content
    assert isinstance(first_pass, str)
    assert isinstance(second_pass, str)
    assert first_pass.count("<bound_skills") == 1
    assert second_pass.count("<bound_skills") == 1


def test_skill_select_tool_description_is_static_without_embedded_xml() -> None:
    skills = [_skill("alpha_skill"), _skill("beta_skill")]
    tool = create_select_skill_tool(skills, _StubSkillBackend())  # type: ignore[arg-type]
    from myrm_agent_harness.agent._internals._agent_build import _weave_dynamic_schemas

    woven = _weave_dynamic_schemas([tool])
    description = woven[0].description or ""
    assert "<skills>" not in description
    assert "alpha_skill" not in description
    assert "<bound_skills>" in description
    assert "skill_search_tool" not in description
    assert "hidden_count" not in description
    assert description.rstrip() == build_skill_select_static_description().rstrip()


def test_skill_select_tool_description_unchanged_when_skill_bind_size_varies() -> None:
    from myrm_agent_harness.agent._internals._agent_build import _weave_dynamic_schemas

    many_skills = [_skill(f"skill_{idx}_skill") for idx in range(25)]
    sparse_tool = create_select_skill_tool(
        many_skills[:1],
        _StubSkillBackend(),  # type: ignore[arg-type]
    )
    dense_tool = create_select_skill_tool(
        many_skills,
        _StubSkillBackend(),  # type: ignore[arg-type]
    )
    sparse_woven = _weave_dynamic_schemas([sparse_tool])[0]
    dense_woven = _weave_dynamic_schemas([dense_tool])[0]
    assert sparse_woven.description == dense_woven.description


def test_metadata_summary_routing_rules_include_search_when_hidden() -> None:
    from myrm_agent_harness.agent.skills.runtime.registry import get_metadata_summary

    inline = get_metadata_summary([_skill("alpha_skill")], hidden_skill_count=0)
    hidden = get_metadata_summary([_skill("alpha_skill")], hidden_skill_count=3)
    assert "skill_search_tool" not in inline
    assert "skill_search_tool" in hidden


def test_metadata_summary_all_hidden_still_emits_search_routing() -> None:
    from myrm_agent_harness.agent.skills.runtime.registry import get_metadata_summary

    summary = get_metadata_summary([], hidden_skill_count=25)
    assert "routing_rules" in summary
    assert "skill_search_tool" in summary
    assert "No skills available" not in summary


def test_bound_skills_block_includes_hidden_count_attribute() -> None:
    block = build_bound_skills_block([_skill("alpha_skill")], hidden_skill_count=5)
    assert 'hidden_count="5"' in block


def test_empty_skills_strips_stale_catalog_without_reinject() -> None:
    stale = '<bound_skills hash="x">\n<skills></skills>\n</bound_skills>\n\nhello'
    messages = [HumanMessage(content=stale)]
    ensure_skill_catalog_in_messages(messages, [])

    first = messages[0]
    assert isinstance(first.content, str)
    assert "<bound_skills" not in first.content
    assert first.content == "hello"


def test_multimodal_first_human_message_prepends_catalog() -> None:
    messages = [
        HumanMessage(
            content=[
                {"type": "text", "text": "describe this image"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/x.png"},
                },
            ]
        )
    ]
    ensure_skill_catalog_in_messages(messages, [_skill("alpha_skill")])

    first = messages[0]
    assert isinstance(first.content, list)
    text_part = first.content[0]
    assert isinstance(text_part, dict)
    assert text_part["type"] == "text"
    text = text_part.get("text")
    assert isinstance(text, str)
    assert text.startswith("<bound_skills")
    assert "describe this image" in text


def test_agent_switch_catalog_refresh_replaces_stale_block() -> None:
    stale = (
        '<bound_skills hash="agent-a">\n<skills><skill name="old_skill"/></skills>\n</bound_skills>\n\nfirst question'
    )
    messages = [HumanMessage(content=stale), HumanMessage(content="follow up")]
    ensure_skill_catalog_in_messages(messages, [_skill("new_skill")])

    first = messages[0]
    assert isinstance(first.content, str)
    assert "old_skill" not in first.content
    assert "new_skill" in first.content
    assert first.content.count("<bound_skills") == 1


def test_ensure_skill_catalog_sets_hidden_count_on_large_bind() -> None:
    many = [_skill(f"skill_{idx}_skill") for idx in range(25)]
    messages = [HumanMessage(content="question")]
    ensure_skill_catalog_in_messages(messages, many)

    first = messages[0]
    assert isinstance(first.content, str)
    assert 'hidden_count="' in first.content


def test_ensure_skill_catalog_no_ops_without_human_message() -> None:
    messages = [AIMessage(content="assistant only")]
    ensure_skill_catalog_in_messages(messages, [_skill("alpha_skill")])
    assert messages[0].content == "assistant only"


def test_ensure_skill_catalog_no_ops_on_empty_messages() -> None:
    messages: list[HumanMessage] = []
    ensure_skill_catalog_in_messages(messages, [_skill("alpha_skill")])
    assert messages == []


def test_resolve_catalog_display_skills_prefers_always_skills_when_over_threshold() -> None:
    from myrm_agent_harness.agent.skills.runtime.catalog_display import (
        resolve_catalog_display_skills,
    )

    skills = [
        SkillMetadata(
            name=f"skill_{idx}_skill",
            description="x",
            model_invocable=True,
            available=True,
            always=(idx == 0),
        )
        for idx in range(25)
    ]
    resolution = resolve_catalog_display_skills(skills)
    assert resolution.display_skills[0].name == "skill_0_skill"
    assert len(resolution.display_skills) == 11
    assert resolution.hidden_skill_count == 14

    from myrm_agent_harness.agent.skills.runtime.catalog_display import (
        resolve_catalog_display_skills,
    )

    core = SkillMetadata(
        storage_skill_id="core-id",
        name="core_skill",
        description="core",
        model_invocable=True,
        available=True,
    )
    other = SkillMetadata(
        storage_skill_id="other-id",
        name="other_skill",
        description="other",
        model_invocable=True,
        available=True,
    )
    resolution = resolve_catalog_display_skills(
        [core, other],
        skill_configs={"core-id": {"is_core": True}},
    )
    assert [skill.name for skill in resolution.display_skills] == ["core_skill"]
    assert resolution.hidden_skill_count == 1


def test_resolve_catalog_display_skills_filters_by_available_tools() -> None:
    from myrm_agent_harness.agent.skills.runtime.catalog_display import (
        resolve_catalog_display_skills,
    )

    gated = SkillMetadata(
        name="needs_web_skill",
        description="gated",
        model_invocable=True,
        available=True,
        requires_tools=["web_search_tool"],
    )
    plain = SkillMetadata(
        name="plain_skill",
        description="plain",
        model_invocable=True,
        available=True,
    )
    with_tools = resolve_catalog_display_skills(
        [gated, plain],
        available_tool_names=frozenset(["web_search_tool"]),
    )
    without_tools = resolve_catalog_display_skills(
        [gated, plain],
        available_tool_names=frozenset(),
    )
    assert {skill.name for skill in with_tools.filtered_skills} == {
        "needs_web_skill",
        "plain_skill",
    }
    assert {skill.name for skill in without_tools.filtered_skills} == {"plain_skill"}
