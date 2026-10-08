"""Tests for explicit skill injection (SkillAgent._preload_explicit_skill).

Covers:
- Pattern matching for [use skill_name]
- SOP injection with strong signal
- ${SKILL_DIR} template variable replacement
- Auxiliary file listing
- Graceful degradation (skill not found, empty SOP, backend errors)
- Edge cases (multimodal query, multiline args, special characters)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.skill_agent.skill_reference import parse_use_tag
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust

_IMAGE_BLOCK: dict[str, object] = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _StubSkillBackend:
    """Minimal stub satisfying SkillBackend protocol for testing."""

    content_map: dict[str, str] = field(default_factory=dict)
    resource_map: dict[str, list[str]] = field(default_factory=dict)

    async def list_skills(self) -> list[SkillMetadata]:
        return []

    async def load_skills(self, ids: list[str]) -> list[SkillMetadata]:
        return []

    async def get_skill_content(self, skill_id: str) -> str:
        if skill_id in self.content_map:
            return self.content_map[skill_id]
        raise FileNotFoundError(f"Skill {skill_id} not found")

    async def get_skill_resources(self, skill_id: str, path: str) -> bytes:
        raise NotImplementedError

    async def list_skill_resources(self, skill_id: str) -> list[str]:
        return list(self.resource_map.get(skill_id, []))


def _make_skill(
    name: str = "test_skill",
    storage_skill_id: str | None = "test_skill",
    storage_path: str | None = None,
    trust: SkillTrust = SkillTrust.TRUSTED,
    user_invocable: bool = True,
) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"Test skill: {name}",
        storage_skill_id=storage_skill_id,
        storage_path=storage_path,
        trust=trust,
        user_invocable=user_invocable,
    )


def _make_agent(
    skills: list[SkillMetadata] | None = None,
    backend: _StubSkillBackend | None = None,
) -> SkillAgent:
    """Create a minimal SkillAgent for testing preload logic."""
    AsyncMock()
    agent = SkillAgent.__new__(SkillAgent)
    agent.skill_backend = backend
    agent._desired_skill_ids = None
    agent._trusted_skill_ids = frozenset()

    if skills is not None and backend is not None:

        async def _patched_list() -> list[SkillMetadata]:
            return skills

        backend.list_skills = _patched_list

    return agent


# ---------------------------------------------------------------------------
# Pattern matching tests
# ---------------------------------------------------------------------------


class TestUseTagGrammar:
    """Tests for parse_use_tag, the grammar of the leading [use skill_name] tag."""

    def test_basic_match(self) -> None:
        tag = parse_use_tag("[use daily_report_skill] generate today's report")
        assert tag is not None
        assert tag.references == ("daily_report_skill",)
        assert tag.text == "generate today's report"

    def test_literal_tag_is_kept_for_hosts_that_decorate_the_text(self) -> None:
        tag = parse_use_tag("[use a, b]   do it")
        assert tag is not None
        assert tag.tag == "[use a, b]"
        assert tag.text == "do it"

    def test_no_args(self) -> None:
        tag = parse_use_tag("[use deploy_skill]")
        assert tag is not None
        assert tag.references == ("deploy_skill",)
        assert tag.text == ""

    def test_with_args_trailing_space(self) -> None:
        tag = parse_use_tag("[use deploy_skill] staging  ")
        assert tag is not None
        assert tag.references == ("deploy_skill",)
        assert tag.text == "staging"

    def test_hyphenated_skill_name(self) -> None:
        tag = parse_use_tag("[use my-great-skill] do something")
        assert tag is not None
        assert tag.references == ("my-great-skill",)

    def test_no_match_plain_text(self) -> None:
        assert parse_use_tag("Just a normal message") is None

    def test_no_match_middle_of_text(self) -> None:
        assert parse_use_tag("Please [use test_skill] now") is None

    def test_no_match_behind_a_prefix_the_host_added(self) -> None:
        assert parse_use_tag("[Inbound channel message] channel=x\n---\n\n[use test_skill] now") is None

    def test_multiline_args(self) -> None:
        tag = parse_use_tag("[use test_skill] line1\nline2\nline3")
        assert tag is not None
        assert tag.text == "line1\nline2\nline3"

    def test_empty_skill_name_no_match(self) -> None:
        assert parse_use_tag("[use ] something") is None
        assert parse_use_tag("[use ,] something") is None

    def test_multi_skill_comma_separated(self) -> None:
        tag = parse_use_tag("[use skill_a,skill_b,skill_c] do it")
        assert tag is not None
        assert tag.references == ("skill_a", "skill_b", "skill_c")
        assert tag.text == "do it"

    def test_multi_skill_with_spaces(self) -> None:
        tag = parse_use_tag("[use skill_a, skill_b] args")
        assert tag is not None
        assert tag.references == ("skill_a", "skill_b")

    def test_multi_skill_no_args(self) -> None:
        tag = parse_use_tag("[use a,b]")
        assert tag is not None
        assert tag.references == ("a", "b")
        assert tag.text == ""

    def test_trailing_comma(self) -> None:
        tag = parse_use_tag("[use a,b,] args")
        assert tag is not None
        assert tag.references == ("a", "b")


# ---------------------------------------------------------------------------
# Preload integration tests
# ---------------------------------------------------------------------------


class TestPreloadExplicitSkill:
    """Tests for SkillAgent._preload_explicit_skill."""

    @pytest.mark.asyncio
    async def test_successful_preload(self) -> None:
        """Normal path: skill found, SOP loaded, query rewritten."""
        skill = _make_skill(name="daily_report_skill", storage_skill_id="daily_report_skill")
        backend = _StubSkillBackend(content_map={"daily_report_skill": "# Daily Report\n\nGenerate reports."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill(
            "[use daily_report_skill] generate today's report"
        )

        assert matched is not None
        assert matched.name == "daily_report_skill"
        assert "[IMPORTANT:" in query
        assert "daily_report_skill" in query
        assert "Do NOT call skill_select_tool" in query
        assert "# Daily Report" in query
        assert "generate today's report" in query

    @pytest.mark.asyncio
    async def test_preload_records_usage_stats(self, tmp_path: Path) -> None:
        """[use skill] preload must write .stats.json for Curator."""
        skill_dir = tmp_path / "preload_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# preload\n")

        skill = _make_skill(
            name="preload_skill",
            storage_skill_id="preload_skill",
            storage_path=str(skill_dir),
        )
        backend = _StubSkillBackend(content_map={"preload_skill": "# Preload\n\nSOP."})

        from myrm_agent_harness.backends.skills.stats_collector import (
            SkillStatsCollector,
        )
        from myrm_agent_harness.backends.skills.usage_recorder import (
            flush_skill_usage_stats,
            set_stats_collector,
        )

        collector = SkillStatsCollector(tmp_path)
        set_stats_collector(collector)
        agent = _make_agent(skills=[skill], backend=backend)

        await agent._preload_explicit_skill("[use preload_skill] run task")
        flush_skill_usage_stats()

        stats = collector.get_stats(skill_dir)
        assert stats.call_count == 1
        assert stats.success_count == 1
        set_stats_collector(None)

    @pytest.mark.asyncio
    async def test_user_args_preserved(self) -> None:
        """User arguments after [use] must appear at the end of the injected query."""
        skill = _make_skill(name="test_skill")
        backend = _StubSkillBackend(content_map={"test_skill": "# Test\n\nSOP content."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, _, _preloaded = await agent._preload_explicit_skill("[use test_skill] my custom args here")
        assert query.endswith("my custom args here")

    @pytest.mark.asyncio
    async def test_no_args(self) -> None:
        """[use skill_name] without args should still inject SOP."""
        skill = _make_skill(name="test_skill")
        backend = _StubSkillBackend(content_map={"test_skill": "# Test\n\nSOP."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use test_skill]")
        assert matched is not None
        assert "# Test" in query
        assert not query.rstrip().endswith("\n\n")

    @pytest.mark.asyncio
    async def test_fallback_no_backend(self) -> None:
        """Without a skill_backend, query should pass through unchanged."""
        agent = _make_agent(skills=None, backend=None)
        agent.skill_backend = None

        query, matched, _preloaded = await agent._preload_explicit_skill("[use test_skill] args")
        assert matched is None
        assert query == "[use test_skill] args"

    @pytest.mark.asyncio
    async def test_fallback_skill_not_found(self) -> None:
        """If skill name doesn't exist, query passes through for Rule 6 fallback."""
        backend = _StubSkillBackend()
        agent = _make_agent(skills=[], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use nonexistent_skill] do something")
        assert matched is None
        assert query == "[use nonexistent_skill] do something"

    @pytest.mark.asyncio
    async def test_fallback_sop_load_error(self) -> None:
        """If SOP loading throws, query passes through unchanged."""
        skill = _make_skill(name="broken_skill", storage_skill_id="broken_skill")
        backend = _StubSkillBackend()
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use broken_skill] args")
        assert matched is None
        assert query == "[use broken_skill] args"

    @pytest.mark.asyncio
    async def test_fallback_empty_sop(self) -> None:
        """If SOP is empty, query passes through unchanged."""
        skill = _make_skill(name="empty_skill", storage_skill_id="empty_skill")
        backend = _StubSkillBackend(content_map={"empty_skill": ""})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use empty_skill] args")
        assert matched is None
        assert query == "[use empty_skill] args"

    @pytest.mark.asyncio
    async def test_non_use_query_unchanged(self) -> None:
        """Regular messages should not trigger preloading."""
        backend = _StubSkillBackend()
        agent = _make_agent(skills=[], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("Just a normal question")
        assert matched is None
        assert query == "Just a normal question"

    @pytest.mark.asyncio
    async def test_strong_signal_format(self) -> None:
        """Verify the strong signal header matches the expected format."""
        skill = _make_skill(name="test_skill")
        backend = _StubSkillBackend(content_map={"test_skill": "# Test\n\nContent."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, _, _preloaded = await agent._preload_explicit_skill("[use test_skill] args")
        first_line = query.split("\n")[0]
        assert first_line.startswith("[IMPORTANT:")
        assert "test_skill" in first_line
        assert "preloaded" in first_line.lower()

    @pytest.mark.asyncio
    async def test_unavailable_skill_includes_warning(self) -> None:
        """Unavailable skills should still load but include a WARNING in the signal."""
        skill = _make_skill(name="ffmpeg_skill", storage_skill_id="ffmpeg_skill")
        skill.available = False
        skill.unavailable_reason = "ffmpeg not found on PATH"
        backend = _StubSkillBackend(content_map={"ffmpeg_skill": "# FFmpeg\n\nConvert videos."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use ffmpeg_skill] convert file.mp4")
        assert matched is not None
        assert "WARNING" in query
        assert "UNAVAILABLE" in query
        assert "ffmpeg not found on PATH" in query
        assert "# FFmpeg" in query

    @pytest.mark.asyncio
    async def test_available_skill_no_warning(self) -> None:
        """Available skills should NOT include an UNAVAILABLE warning."""
        skill = _make_skill(name="test_skill")
        backend = _StubSkillBackend(content_map={"test_skill": "# Test\n\nContent."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, _, _preloaded = await agent._preload_explicit_skill("[use test_skill] args")
        assert "UNAVAILABLE" not in query
        assert "WARNING" not in query

    @pytest.mark.asyncio
    async def test_unavailable_skill_default_reason(self) -> None:
        """Unavailable skill with no explicit reason uses default message."""
        skill = _make_skill(name="gpu_skill", storage_skill_id="gpu_skill")
        skill.available = False
        skill.unavailable_reason = None
        backend = _StubSkillBackend(content_map={"gpu_skill": "# GPU\n\nAccelerate."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use gpu_skill] run")
        assert matched is not None
        assert "dependency requirements not met" in query

    @pytest.mark.asyncio
    async def test_get_skill_document_exception_fallback(self) -> None:
        """If get_skill_document raises an unexpected exception, fallback gracefully."""
        from unittest.mock import patch

        skill = _make_skill(name="crash_skill", storage_skill_id="crash_skill")
        backend = _StubSkillBackend(content_map={"crash_skill": "# Crash\n\nContent."})
        agent = _make_agent(skills=[skill], backend=backend)

        with patch(
            "myrm_agent_harness.agent.meta_tools.skills.select.get_skill_document",
            side_effect=RuntimeError("unexpected failure"),
        ):
            query, matched, _preloaded = await agent._preload_explicit_skill("[use crash_skill] test")

        assert matched is None
        assert query == "[use crash_skill] test"

    @pytest.mark.asyncio
    async def test_preload_with_file_listing(self, tmp_path: Path) -> None:
        """Successful preload with auxiliary files includes file listing."""

        skill_dir = tmp_path / "deploy_skill"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "deploy.sh").write_text("#!/bin/bash\necho deploy")

        skill = _make_skill(
            name="deploy_skill",
            storage_skill_id="deploy_skill",
            storage_path=str(skill_dir),
        )
        backend = _StubSkillBackend(
            content_map={"deploy_skill": "# Deploy\n\nRun deploy."},
            resource_map={"deploy_skill": ["scripts/deploy.sh"]},
        )
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use deploy_skill] prod")
        assert matched is not None
        assert "[Linked files]" in query
        assert "scripts/deploy.sh" in query
        assert "prod" in query

    @pytest.mark.asyncio
    async def test_sop_with_error_string_fallback(self) -> None:
        """SOP containing an error marker should trigger fallback."""
        skill = _make_skill(name="err_skill", storage_skill_id="err_skill")
        backend = _StubSkillBackend(content_map={"err_skill": "# err_skill\n\nError: failed to load skill content"})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use err_skill] test")
        assert matched is None
        assert query == "[use err_skill] test"

    # -- Multi-skill bundle tests --

    @pytest.mark.asyncio
    async def test_bundle_two_skills(self) -> None:
        """Comma-separated skills should merge SOPs with bundle header."""
        s1 = _make_skill(name="skill_a", storage_skill_id="skill_a")
        s2 = _make_skill(name="skill_b", storage_skill_id="skill_b")
        backend = _StubSkillBackend(
            content_map={
                "skill_a": "# Skill A\n\nDo A.",
                "skill_b": "# Skill B\n\nDo B.",
            }
        )
        agent = _make_agent(skills=[s1, s2], backend=backend)

        query, matched, preloaded = await agent._preload_explicit_skill("[use skill_a,skill_b] run both")
        assert matched is not None
        assert matched.name == "skill_a"
        assert len(preloaded) == 2
        assert {skill.name for skill in preloaded} == {"skill_a", "skill_b"}
        assert "skills have been preloaded as a bundle" in query
        assert "--- Skill: skill_a ---" in query
        assert "--- Skill: skill_b ---" in query
        assert "# Skill A" in query
        assert "# Skill B" in query
        assert query.rstrip().endswith("run both")

    @pytest.mark.asyncio
    async def test_bundle_partial_skill_not_found(self) -> None:
        """If one skill in bundle is missing, load only the found ones."""
        s1 = _make_skill(name="found_skill", storage_skill_id="found_skill")
        backend = _StubSkillBackend(content_map={"found_skill": "# Found\n\nContent."})
        agent = _make_agent(skills=[s1], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use found_skill,missing_skill] args")
        assert matched is not None
        assert matched.name == "found_skill"
        assert "# Found" in query
        assert "missing_skill" not in query.split("---")[-1]
        assert "preloaded" in query.lower()

    @pytest.mark.asyncio
    async def test_bundle_all_skills_missing(self) -> None:
        """If all skills in bundle are missing, query passes through unchanged."""
        backend = _StubSkillBackend()
        agent = _make_agent(skills=[], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use x,y,z] args")
        assert matched is None
        assert query == "[use x,y,z] args"

    @pytest.mark.asyncio
    async def test_bundle_token_budget_enforcement(self) -> None:
        """When combined SOPs exceed _TOKEN_BUDGET_MAX, later skills are skipped."""
        big_sop = "# Big Skill\n\n" + ("x" * 12000)
        small_sop = "# Small Skill\n\nTiny."
        s1 = _make_skill(name="big", storage_skill_id="big")
        s2 = _make_skill(name="small", storage_skill_id="small")
        backend = _StubSkillBackend(content_map={"big": big_sop, "small": small_sop})
        agent = _make_agent(skills=[s1, s2], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use big,small] test")
        assert matched is not None
        assert "# Big Skill" in query
        assert "# Small Skill" not in query

    @pytest.mark.asyncio
    async def test_single_skill_uses_single_header(self) -> None:
        """Single skill should use 'has been preloaded', not 'bundle' header."""
        skill = _make_skill(name="solo", storage_skill_id="solo")
        backend = _StubSkillBackend(content_map={"solo": "# Solo\n\nContent."})
        agent = _make_agent(skills=[skill], backend=backend)

        query, _, _preloaded = await agent._preload_explicit_skill("[use solo] go")
        assert "bundle" not in query.lower()
        assert '"solo" has been preloaded' in query

    @pytest.mark.asyncio
    async def test_bundle_with_instruction_in_user_args(self) -> None:
        """[instruction: ...] in user_args should be forwarded as-is."""
        s1 = _make_skill(name="a", storage_skill_id="a")
        s2 = _make_skill(name="b", storage_skill_id="b")
        backend = _StubSkillBackend(content_map={"a": "# A\n\nDo A.", "b": "# B\n\nDo B."})
        agent = _make_agent(skills=[s1, s2], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use a,b] [instruction: be concise] do it")
        assert matched is not None
        assert "[instruction: be concise] do it" in query


# ---------------------------------------------------------------------------
# ${SKILL_DIR} template variable tests
# ---------------------------------------------------------------------------


class TestSkillDirTemplateVariable:
    """Tests for ${SKILL_DIR} replacement in get_skill_document."""

    @pytest.mark.asyncio
    async def test_skill_dir_replacement(self) -> None:
        """${SKILL_DIR} in SOP should be replaced with storage_path."""
        skill = _make_skill(
            name="script_skill",
            storage_skill_id="script_skill",
            storage_path="/home/user/.claude/skills/script_skill",
        )
        sop_with_template = "# Script\n\nRun: `python3 ${SKILL_DIR}/scripts/main.py`"
        backend = _StubSkillBackend(content_map={"script_skill": sop_with_template})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use script_skill] run it")
        assert matched is not None
        assert "${SKILL_DIR}" not in query
        assert "/home/user/.claude/skills/script_skill/scripts/main.py" in query

    @pytest.mark.asyncio
    async def test_no_skill_dir_when_no_storage_path(self) -> None:
        """Without storage_path, ${SKILL_DIR} should remain as-is."""
        skill = _make_skill(
            name="mcp_skill",
            storage_skill_id="mcp_skill",
            storage_path=None,
        )
        sop = "# MCP\n\nSee ${SKILL_DIR} for details."
        backend = _StubSkillBackend(content_map={"mcp_skill": sop})
        agent = _make_agent(skills=[skill], backend=backend)

        query, matched, _preloaded = await agent._preload_explicit_skill("[use mcp_skill] test")
        assert matched is not None
        assert "${SKILL_DIR}" in query


class TestPreloadExplicitSkillInBlocks:
    """A message with attachments reaches the agent as content blocks; the user's words are the first one."""

    @staticmethod
    def _agent_with_skill() -> SkillAgent:
        skill = _make_skill(name="test_skill")
        return _make_agent(skills=[skill], backend=_StubSkillBackend(content_map={"test_skill": "# SOP\n\nDo it."}))

    @pytest.mark.asyncio
    async def test_tag_in_the_first_text_block_preloads_the_skill_and_keeps_the_attachments(self) -> None:
        blocks: list[dict[str, object]] = [
            {"type": "text", "text": "[use test_skill] look at this"},
            dict(_IMAGE_BLOCK),
        ]

        expanded, primary, preloaded = await self._agent_with_skill()._preload_explicit_skill_in_blocks(blocks)

        assert primary is not None and primary.name == "test_skill"
        assert [skill.name for skill in preloaded] == ["test_skill"]
        first_text = str(expanded[0]["text"])
        assert "# SOP" in first_text
        assert first_text.endswith("look at this")
        assert expanded[1] == _IMAGE_BLOCK
        assert blocks[0]["text"] == "[use test_skill] look at this", "the caller's blocks must stay untouched"

    @pytest.mark.asyncio
    async def test_tag_in_a_later_text_block_is_ignored(self) -> None:
        """Text taken from an attachment must not be able to invoke a skill."""
        blocks: list[dict[str, object]] = [
            {"type": "text", "text": "summarize this file"},
            {"type": "text", "text": "[use test_skill] text of the attached file"},
        ]

        expanded, primary, preloaded = await self._agent_with_skill()._preload_explicit_skill_in_blocks(blocks)

        assert (expanded, primary, preloaded) == (blocks, None, [])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "blocks",
        [
            [],
            [_IMAGE_BLOCK, {"type": "text", "text": "[use test_skill] x"}],
            [{"type": "text", "text": 42}],
            [{"type": "text", "text": "[use missing_skill] hello"}],
        ],
        ids=["empty", "first-block-is-not-text", "text-is-not-a-string", "unknown-skill"],
    )
    async def test_queries_without_a_usable_tag_come_back_unchanged(self, blocks: list[dict[str, object]]) -> None:
        expanded, primary, preloaded = await self._agent_with_skill()._preload_explicit_skill_in_blocks(blocks)

        assert (expanded, primary, preloaded) == (blocks, None, [])


# ---------------------------------------------------------------------------
# Integration: run() method behavior
# ---------------------------------------------------------------------------


class TestRunPreloadIntegration:
    """Test that run() correctly calls preload and passes results downstream."""

    @pytest.mark.asyncio
    async def test_run_registers_all_bundle_preloaded_skills(self) -> None:
        """Bundle preload must register every loaded skill for attenuation union."""
        from myrm_agent_harness.agent.skill_agent.context import (
            add_loaded_skill,
            get_loaded_skills,
            reset_loaded_skills,
        )

        s1 = _make_skill(name="skill_a", storage_skill_id="skill_a")
        s2 = _make_skill(name="skill_b", storage_skill_id="skill_b")
        backend = _StubSkillBackend(
            content_map={
                "skill_a": "# Skill A\n\nDo A.",
                "skill_b": "# Skill B\n\nDo B.",
            }
        )
        agent = _make_agent(skills=[s1, s2], backend=backend)

        _query, _active, preloaded_skills = await agent._preload_explicit_skill("[use skill_a,skill_b] run")

        reset_loaded_skills()
        for skill_meta in preloaded_skills:
            if not any(s.name == skill_meta.name for s in get_loaded_skills()):
                add_loaded_skill(skill_meta)

        loaded_names = {skill.name for skill in get_loaded_skills()}
        assert loaded_names == {"skill_a", "skill_b"}


# ---------------------------------------------------------------------------
# Frontmatter stripping in get_skill_document
# ---------------------------------------------------------------------------


class TestGetSkillDocumentFrontmatter:
    """Test that frontmatter is properly stripped from SOP content."""

    @pytest.mark.asyncio
    async def test_strips_yaml_frontmatter(self) -> None:
        from myrm_agent_harness.agent.meta_tools.skills.select import get_skill_document

        sop = "---\nname: test\ndescription: hello\n---\n# My Skill\n\nDo stuff."
        skill = _make_skill(name="fm_skill", storage_skill_id="fm_skill")
        backend = _StubSkillBackend(content_map={"fm_skill": sop})

        result = await get_skill_document(skill, backend)  # type: ignore[arg-type]
        assert result.startswith("# My Skill")
        assert "---" not in result.split("# My Skill")[0]

    @pytest.mark.asyncio
    async def test_adds_title_if_missing(self) -> None:
        from myrm_agent_harness.agent.meta_tools.skills.select import get_skill_document

        sop = "Just some content without a heading."
        skill = _make_skill(name="notitle_skill", storage_skill_id="notitle_skill")
        backend = _StubSkillBackend(content_map={"notitle_skill": sop})

        result = await get_skill_document(skill, backend)  # type: ignore[arg-type]
        assert result.startswith("# notitle_skill")
