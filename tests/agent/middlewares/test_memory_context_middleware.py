"""Test memory_context_middleware.

Validates helper functions (_format_memory_context, _has_memory_context),
cold/warm adaptive prompt, privileged vs learned split, RecallMode,
ContextVar integration, and awrap_model_call injection semantics.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.memory_context_format import (
    _COLD_START_CONTEXT,
    MEMORY_CONTEXT_MARKER,
    MEMORY_UNTRUSTED_OPEN_MARKER,
    _escape_xml_item,
    _format_memory_context,
    _has_memory_context,
    _partition_budget_sections,
)
from myrm_agent_harness.agent.middlewares.memory_context_middleware import (
    memory_context_middleware,
)
from myrm_agent_harness.toolkits.memory.config import RecallMode

_EMPTY_LEARNED: dict[str, list[dict[str, str]]] = {"learned_rules": [], "learned_preferences": []}


# ---------------------------------------------------------------------------
# _has_memory_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_memory_context_detects_marker():
    messages_with = [
        SystemMessage(content="System prompt"),
        SystemMessage(content="<user_memory_context>\nUser info\n</user_memory_context>"),
        HumanMessage(content="Hello"),
    ]
    assert _has_memory_context(messages_with) is True

    messages_untrusted_only = [
        SystemMessage(content="System prompt"),
        HumanMessage(
            content=(
                '[SECURITY NOTICE: UNTRUSTED external content below. ]\n<<<UNTRUSTED_DATA id="abc">>>\nx\n<<<END_UNTRUSTED_DATA id="abc">>>'
            )
        ),
    ]
    assert _has_memory_context(messages_untrusted_only) is True

    messages_without = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="Hello"),
    ]
    assert _has_memory_context(messages_without) is False


def test_has_memory_context_skips_non_string_parts():
    """Multimodal / structured content must not crash idempotency scan."""
    block = [{"type": "text", "text": "hello"}]
    msgs = [
        SystemMessage(content="sys"),
        HumanMessage(content=block),  # type: ignore[arg-type]
    ]
    assert _has_memory_context(msgs) is False


def test_partition_budget_skips_sections_with_empty_item_lists():
    from myrm_agent_harness.agent.security.guards.prompt_budget import BudgetedSection

    s, u = _partition_budget_sections(
        [BudgetedSection("EmptyStable", [], priority=1)],
        [BudgetedSection("EmptyLearned", [], priority=2)],
        max_tokens=500,
        truncation_message="X",
    )
    assert s == ""
    assert u == ""


def test_partition_budget_header_exceeds_budget_yields_empty_bodies():
    """When even the first section header does not fit, nothing is allocated (no truncation tail)."""
    from myrm_agent_harness.agent.security.guards.prompt_budget import BudgetedSection

    s, u = _partition_budget_sections(
        [BudgetedSection("Wide", ["ok"], priority=1)],
        [],
        max_tokens=0,
        truncation_message="SHOULD_NOT_APPEAR",
    )
    assert s == ""
    assert u == ""
    assert "SHOULD_NOT_APPEAR" not in s + u


def test_partition_budget_line_overflow_with_empty_accepted_lines_skips_block():
    """Header fits but first bullet cannot — section produces no block (continue path)."""
    from myrm_agent_harness.agent.security.guards.prompt_budget import BudgetedSection

    huge = "Z" * 40
    s, _u = _partition_budget_sections(
        [BudgetedSection("T", [huge], priority=1)],
        [],
        max_tokens=2,
        truncation_message="",
    )
    assert s == ""


def test_partition_budget_post_truncation_notice_appends_after_nonempty_untrusted():
    """truncation tail joins onto a partially filled untrusted body (coverage for line 139-141)."""
    from myrm_agent_harness.agent.security.guards.prompt_budget import BudgetedSection

    parts = BudgetedSection(
        "Mix",
        [
            _escape_xml_item("kept-short"),
            _escape_xml_item("tail" + "y" * 9000),
        ],
        priority=1,
    )
    stable, unst = _partition_budget_sections(
        [],
        [parts],
        max_tokens=48,
        truncation_message="NOTICE_TAIL",
    )
    assert stable == ""
    assert "kept-short" in unst
    assert "NOTICE_TAIL" in unst


def test_partition_budget_appends_truncation_note_when_trimmed():
    """When oversized sections are clipped, truncation_message is stitched into whichever side retained content."""
    from myrm_agent_harness.agent.security.guards.prompt_budget import BudgetedSection

    stable_secs = [BudgetedSection("High", ["kept-short"], priority=1)]
    long_blob = "L" * 8000
    untrusted_esc = [
        BudgetedSection("LowPri", [_escape_xml_item(long_blob)], priority=80),
    ]
    s, u = _partition_budget_sections(
        stable_secs,
        untrusted_esc,
        max_tokens=240,
        truncation_message="CUT_MARKER",
    )
    combo = (s or "") + (u or "")
    assert "CUT_MARKER" in combo


def test_format_memory_context_budget_truncates_lower_priority_sections():
    """Very large stable + learned sets share one budget — lower priority sections disappear first."""
    wall = "w" * 1200
    ctx = {"global_profile": {f"k{i}": wall for i in range(60)}}
    learned = {
        "learned_rules": [],
        "learned_preferences": [{"content": "p"}, {"content": "q" + "z" * 8000}],
    }
    stable, untrusted = _format_memory_context(ctx, learned)
    assert stable is not None
    must_have = "... (Some lower-priority memory items were truncated"
    assert must_have in (stable + (untrusted or ""))


def test_format_learned_escapes_xml_in_items_for_envelope():
    learned = {
        "learned_rules": [],
        "learned_preferences": [{"content": "use <script>"}],
    }
    _stable, untrusted = _format_memory_context({}, learned)
    assert untrusted is not None
    assert "<script>" not in untrusted
    assert "&lt;script&gt;" in untrusted


# ---------------------------------------------------------------------------
# _format_memory_context — static context
# ---------------------------------------------------------------------------


def test_format_empty_returns_cold_start():
    """Empty context produces cold start guidance (stable only)."""
    stable, untrusted = _format_memory_context({}, _EMPTY_LEARNED)
    assert stable == _COLD_START_CONTEXT
    assert untrusted is None
    assert "Discovery Mode" in stable
    assert MEMORY_CONTEXT_MARKER in stable
    assert "conversation_search" not in stable

    stable2, untrusted2 = _format_memory_context(
        {"global_profile": {}, "rules": [], "agent_instructions": []}, _EMPTY_LEARNED
    )
    assert stable2 == _COLD_START_CONTEXT
    assert untrusted2 is None


def test_format_memory_search_omits_conversation_search_by_default():
    learned = {
        "learned_preferences": [{"content": "Prefers dark mode", "id": "p1"}],
        "learned_rules": [],
    }
    _stable, untrusted = _format_memory_context({}, learned)
    assert untrusted is not None
    assert "memory_recall" in untrusted
    assert "conversation_search" not in untrusted


def test_format_memory_search_includes_conversation_search_when_opt_in():
    learned = {
        "learned_preferences": [{"content": "Prefers dark mode", "id": "p1"}],
        "learned_rules": [],
    }
    _stable, untrusted = _format_memory_context(
        {},
        learned,
        include_conversation_search=True,
    )
    assert untrusted is not None
    assert "conversation_search" in untrusted


def test_format_profile():
    ctx = {"global_profile": {"name": "Alice", "role": "Developer"}}
    stable, untrusted = _format_memory_context(ctx, _EMPTY_LEARNED)
    assert stable is not None
    assert untrusted is None
    assert "# User Context (stable)" in stable
    assert "## Global User Profile" in stable
    assert "name: Alice" in stable
    assert "role: Developer" in stable


def test_format_instructions():
    ctx = {
        "agent_instructions": [
            {"instruction": "Always be concise"},
            {"instruction": "Use Python for examples"},
        ],
    }
    stable, untrusted = _format_memory_context(ctx, _EMPTY_LEARNED)
    assert stable is not None
    assert untrusted is None
    assert "## Your Self-Instructions" in stable
    assert "Always be concise" in stable
    assert "Use Python for examples" in stable


def test_format_rules():
    ctx = {
        "rules": [
            {"trigger": "user asks for help", "action": "provide examples"},
            {"trigger": "error occurs", "action": "log and retry"},
        ],
    }
    stable, untrusted = _format_memory_context(ctx, _EMPTY_LEARNED)
    assert stable is not None
    assert untrusted is None
    assert "## Behavioral Rules" in stable
    assert "When: user asks for help → Do: provide examples" in stable
    assert "When: error occurs → Do: log and retry" in stable


def test_format_complete_static():
    ctx = {
        "global_profile": {"name": "Bob"},
        "agent_instructions": [{"instruction": "Be helpful"}],
        "rules": [{"trigger": "greeting", "action": "respond warmly"}],
    }
    stable, untrusted = _format_memory_context(ctx, _EMPTY_LEARNED)
    assert stable is not None
    assert untrusted is None
    assert "# User Context (stable)" in stable
    assert "## Global User Profile" in stable
    assert "## Your Self-Instructions" in stable
    assert "## Behavioral Rules" in stable
    assert "<user_memory_context>" in stable
    assert "</user_memory_context>" in stable


# ---------------------------------------------------------------------------
# _format_memory_context — learned context
# ---------------------------------------------------------------------------


def test_format_learned_rules():
    learned = {
        "learned_rules": [
            {"trigger": "code review", "action": "use type hints", "content": "..."},
        ],
        "learned_preferences": [],
    }
    stable, untrusted = _format_memory_context({}, learned)
    assert stable is None
    assert untrusted is not None
    assert MEMORY_UNTRUSTED_OPEN_MARKER in untrusted
    assert "Learned Rules" in untrusted
    assert "When: code review" in untrusted and "Do: use type hints" in untrusted


def test_critical_tool_rules_promoted_to_stable():
    """CRITICAL/HIGH tool-scoped rules must appear in stable section, not learned."""
    learned = {
        "learned_rules": [
            {
                "trigger": "use sudo",
                "action": "never use sudo",
                "content": "...",
                "tool_name": "bash_code_execute_tool",
                "tool_rule_priority": "critical",
            },
            {
                "trigger": "code review",
                "action": "use type hints",
                "content": "...",
            },
        ],
        "learned_preferences": [],
    }
    stable, untrusted = _format_memory_context({}, learned)
    assert stable is not None
    assert "Tool Safety Rules" in stable
    assert "never use sudo" in stable
    assert "[bash_code_execute_tool]" in stable
    assert untrusted is not None
    assert "Learned Rules" in untrusted
    assert "use type hints" in untrusted
    assert "never use sudo" not in untrusted


def test_high_priority_tool_rules_also_promoted():
    """HIGH priority rules should also be promoted to stable."""
    learned = {
        "learned_rules": [
            {
                "trigger": "file write",
                "action": "backup first",
                "content": "...",
                "tool_name": "file_tool",
                "tool_rule_priority": "high",
            },
        ],
        "learned_preferences": [],
    }
    stable, _untrusted = _format_memory_context({}, learned)
    assert stable is not None
    assert "Tool Safety Rules" in stable
    assert "backup first" in stable


def test_normal_priority_tool_rules_stay_in_learned():
    """NORMAL priority tool rules stay in the learned (untrusted) section."""
    learned = {
        "learned_rules": [
            {
                "trigger": "search",
                "action": "prefer exact match",
                "content": "...",
                "tool_name": "search_tool",
                "tool_rule_priority": "normal",
            },
        ],
        "learned_preferences": [],
    }
    stable, untrusted = _format_memory_context({}, learned)
    assert stable is None
    assert untrusted is not None
    assert "Learned Rules" in untrusted
    assert "prefer exact match" in untrusted


def test_format_learned_preferences():
    learned = {
        "learned_rules": [],
        "learned_preferences": [
            {"content": "prefers dark theme"},
            {"content": "uses vim keybindings"},
        ],
    }
    stable, untrusted = _format_memory_context({}, learned)
    assert stable is None
    assert untrusted is not None
    assert MEMORY_UNTRUSTED_OPEN_MARKER in untrusted
    assert "## Learned Preferences" in untrusted
    assert "prefers dark theme" in untrusted
    assert "uses vim keybindings" in untrusted


def test_format_mixed_static_and_learned():
    """Stable profile stays in `<user_memory_context>`; learned is untrusted-framed."""
    ctx = {"global_profile": {"name": "Carol"}}
    learned = {
        "learned_rules": [{"trigger": "deploy", "action": "run tests first", "content": "..."}],
        "learned_preferences": [{"content": "uses Python 3.13"}],
    }
    stable, untrusted = _format_memory_context(ctx, learned)
    assert stable is not None
    assert untrusted is not None
    assert "<user_memory_context>" in stable
    assert MEMORY_UNTRUSTED_OPEN_MARKER in untrusted
    assert "User Profile" in stable
    assert "name: Carol" in stable
    assert "Learned Rules" in untrusted and "Learned Preferences" in untrusted
    assert "When: deploy" in untrusted
    assert "uses Python 3.13" in untrusted


def test_format_corrections_from_source_error():
    """Preferences with source_error stay in stable; remaining prefs are untrusted."""
    learned = {
        "learned_rules": [],
        "learned_preferences": [
            {"content": "use ruff instead of flake8", "source_error": "flake8 is deprecated"},
            {"content": "prefers dark theme"},
        ],
    }
    stable, untrusted = _format_memory_context({}, learned)
    assert stable is not None
    assert untrusted is not None
    assert "## Corrections (must follow)" in stable
    assert "use ruff instead of flake8" in stable and "AVOID: flake8 is deprecated" in stable
    assert "## Learned Preferences" in untrusted
    assert "prefers dark theme" in untrusted


def test_format_empty_learned_no_sections():
    """Empty learned lists should not produce Learned sections."""
    stable, untrusted = _format_memory_context({"global_profile": {"name": "Dave"}}, {"learned_rules": [], "learned_preferences": []})
    assert stable is not None
    assert untrusted is None
    assert "## Learned Rules" not in stable
    assert "## Learned Preferences" not in stable


# ---------------------------------------------------------------------------
# ContextVar integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contextvar_integration():
    from myrm_agent_harness.agent._skill_agent_context import get_memory_manager, set_memory_manager

    assert get_memory_manager() is None

    mock_manager = MagicMock()
    mock_manager._config = MagicMock()
    mock_manager._config.max_learned_context_chars = 50000
    mock_manager._config.model_context_tokens = 8000
    mock_manager.user_id = "test_user"

    set_memory_manager(mock_manager)
    assert get_memory_manager() is mock_manager
    assert get_memory_manager().user_id == "test_user"

    set_memory_manager(None)
    assert get_memory_manager() is None


# ---------------------------------------------------------------------------
# inject_memory_context — core middleware
# ---------------------------------------------------------------------------


def _get_raw_inject_fn():
    """Extract the raw async function from the wrapped middleware."""
    return memory_context_middleware.awrap_model_call


def _make_request(
    *, messages: list | None = None, state_messages: list | None = None, has_runtime_context: bool = True
):
    """Build a minimal mock ModelRequest for inject_memory_context."""
    req = MagicMock()
    req.messages = messages or [HumanMessage(content="Hello")]
    req.state = {"messages": state_messages if state_messages is not None else []}

    if has_runtime_context:
        req.runtime = MagicMock()
        req.runtime.context = {"some": "context"}
    else:
        req.runtime = None

    req.override = MagicMock(side_effect=lambda **kwargs: MagicMock(**kwargs))
    return req


class TestInjectMemoryContext:
    """Tests for inject_memory_context middleware function."""

    @pytest.fixture()
    def _inject_fn(self):
        return _get_raw_inject_fn()

    @pytest.mark.asyncio
    async def test_skips_when_marker_in_state_but_not_request(self, _inject_fn):
        """Idempotency: injection already mirrored into graph state."""
        handler = AsyncMock()
        seeded = [
            SystemMessage(content="sys"),
            SystemMessage(content=f"{MEMORY_CONTEXT_MARKER}>x</user_memory_context>"),
            HumanMessage(content="hello"),
        ]
        req = _make_request(
            messages=[SystemMessage(content="sys"), HumanMessage(content="hello")],
            state_messages=list(seeded),
        )
        await _inject_fn(req, handler)
        handler.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_skips_when_marker_already_present(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request(
            messages=[
                SystemMessage(content="sys"),
                SystemMessage(content=f"{MEMORY_CONTEXT_MARKER}>\ndata\n</user_memory_context>"),
                HumanMessage(content="hi"),
            ]
        )
        await _inject_fn(req, handler)
        handler.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_skips_when_no_runtime_context(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request(has_runtime_context=False)
        await _inject_fn(req, handler)
        handler.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_skips_when_no_memory_manager(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request()
        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=None):
            await _inject_fn(req, handler)
        handler.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_injects_context_on_success(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request()

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(return_value={"global_profile": {"name": "Test"}})
        mock_manager.get_learned_context = AsyncMock(return_value={"learned_rules": [], "learned_preferences": []})

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        req.override.assert_called_once()
        call_kwargs = req.override.call_args[1]
        injected_messages = call_kwargs["messages"]

        stable_msgs = [m for m in injected_messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)]
        assert len(stable_msgs) == 1

    @pytest.mark.asyncio
    async def test_gather_outer_failure_returns_without_leak_warnings(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request()
        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID

        async def _static() -> dict[str, object]:
            return {}

        async def _learned() -> dict[str, list[dict[str, str]]]:
            return dict(_EMPTY_LEARNED)

        mock_manager.get_context = _static
        mock_manager.get_learned_context = _learned

        async def exploding_gather(*args: object, **_: object) -> None:
            for maybe in args:
                if asyncio.iscoroutine(maybe):
                    maybe.close()
            raise RuntimeError("simulated_gather_failure")

        with (
            patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager),
            patch(
                "myrm_agent_harness.agent.middlewares.memory_context_middleware.asyncio.gather",
                exploding_gather,
            ),
        ):
            await _inject_fn(req, handler)

        handler.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_short_circuits_when_format_returns_both_none(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request()
        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(return_value={})
        mock_manager.get_learned_context = AsyncMock(return_value=dict(_EMPTY_LEARNED))

        with (
            patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager),
            patch(
                "myrm_agent_harness.agent.middlewares.memory_context_middleware._format_memory_context",
                return_value=(None, None),
            ),
        ):
            await _inject_fn(req, handler)

        handler.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_handles_static_context_failure(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request()

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(side_effect=RuntimeError("db error"))
        mock_manager.get_learned_context = AsyncMock(return_value={"learned_rules": [], "learned_preferences": []})

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        handler.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_handles_learned_context_failure_non_fatal(self, _inject_fn):
        handler = AsyncMock()
        req = _make_request()

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(return_value={"global_profile": {"name": "Test"}})
        mock_manager.get_learned_context = AsyncMock(side_effect=RuntimeError("learned db error"))

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        req.override.assert_called_once()

    @pytest.mark.asyncio
    async def test_cold_start_injects_discovery_prompt(self, _inject_fn):
        """New users (empty context) get cold start discovery guidance as SystemMessage."""
        handler = AsyncMock()
        req = _make_request()

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(return_value={})
        mock_manager.get_learned_context = AsyncMock(return_value={"learned_rules": [], "learned_preferences": []})

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        req.override.assert_called_once()
        call_kwargs = req.override.call_args[1]
        injected_messages = call_kwargs["messages"]
        cold_msgs = [
            m
            for m in injected_messages
            if isinstance(m, SystemMessage) and "Discovery Mode" in str(m.content) and MEMORY_CONTEXT_MARKER in str(m.content)
        ]
        assert len(cold_msgs) == 1

    @pytest.mark.asyncio
    async def test_inserts_after_multiple_system_messages(self, _inject_fn):
        """Memory stable block is inserted after contiguous leading SystemMessages."""
        handler = AsyncMock()
        req = _make_request(
            messages=[
                SystemMessage(content="System prompt 1"),
                SystemMessage(content="System prompt 2"),
                HumanMessage(content="Hello"),
            ]
        )

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(return_value={"global_profile": {"name": "Test"}})
        mock_manager.get_learned_context = AsyncMock(return_value=_EMPTY_LEARNED)

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        req.override.assert_called_once()
        call_kwargs = req.override.call_args[1]
        injected = call_kwargs["messages"]
        sys_count = sum(1 for m in injected if isinstance(m, SystemMessage))
        human_count = sum(1 for m in injected if isinstance(m, HumanMessage))
        assert sys_count == 3
        assert human_count == 1

    @pytest.mark.asyncio
    async def test_learned_only_prefixed_human_before_user_human(self, _inject_fn):
        """Learned envelope HumanMessage sits immediately before the real user utterance."""
        handler = AsyncMock()
        req = _make_request(
            messages=[
                SystemMessage(content="sys"),
                HumanMessage(content="Real user"),
            ]
        )

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u-learned-only"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(return_value={})
        mock_manager.get_learned_context = AsyncMock(
            return_value={
                "learned_rules": [{"trigger": "t", "action": "a", "content": "x"}],
                "learned_preferences": [],
            }
        )

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        req.override.assert_called_once()
        injected = req.override.call_args[1]["messages"]
        ids = [
            ("sys" if isinstance(m, SystemMessage) else ("mem" if isinstance(m, HumanMessage) and MEMORY_UNTRUSTED_OPEN_MARKER in str(m.content) else "user"))
            for m in injected
        ]
        assert ids == ["sys", "mem", "user"]

    @pytest.mark.asyncio
    async def test_skips_injection_when_recall_mode_tools(self, _inject_fn):
        """RecallMode.TOOLS should skip context injection entirely."""
        handler = AsyncMock()
        req = _make_request()

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.TOOLS

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        handler.assert_awaited_once_with(req)
        mock_manager.get_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_aimessage_name_prefix(self, _inject_fn):
        """AIMessages with a 'name' attribute get prefixed with [Agent: {Name}]."""
        from langchain_core.messages import AIMessage
        handler = AsyncMock()
        req = _make_request(
            messages=[
                SystemMessage(content="sys"),
                AIMessage(content="I am a response", name="SubAgentA"),
                HumanMessage(content="Hello"),
            ]
        )

        mock_manager = MagicMock()
        mock_manager._config = MagicMock()
        mock_manager._config.max_learned_context_chars = 50000
        mock_manager._config.model_context_tokens = 8000
        mock_manager.user_id = "u123"
        mock_manager.recall_mode = RecallMode.HYBRID
        mock_manager.get_context = AsyncMock(return_value={})
        mock_manager.get_learned_context = AsyncMock(return_value={"learned_rules": [], "learned_preferences": []})

        with patch("myrm_agent_harness.agent._skill_agent_context.get_memory_manager", return_value=mock_manager):
            await _inject_fn(req, handler)

        req.override.assert_called_once()
        injected_messages = req.override.call_args[1]["messages"]
        ai_msg = next((m for m in injected_messages if isinstance(m, AIMessage)), None)
        assert ai_msg is not None
        assert ai_msg.content.startswith("[Agent: SubAgentA]\n")
        assert "I am a response" in ai_msg.content


# ---------------------------------------------------------------------------
# Scope Boundary — agent instruction vs global memory precedence
# ---------------------------------------------------------------------------


class TestScopeBoundary:
    """Scope boundary declaration in <user_memory_context>."""

    def test_scope_boundary_present_when_stable_body_exists(self):
        ctx = {"global_profile": {"name": "Alice"}}
        stable, _ = _format_memory_context(ctx, _EMPTY_LEARNED)
        assert stable is not None
        assert "Scope Boundary" in stable
        assert "Agent instructions ALWAYS take precedence" in stable
        assert "<user_instructions>" in stable

    def test_scope_boundary_appears_before_user_context_header(self):
        ctx = {"global_profile": {"name": "Bob"}}
        stable, _ = _format_memory_context(ctx, _EMPTY_LEARNED)
        assert stable is not None
        sb_idx = stable.index("Scope Boundary")
        uc_idx = stable.index("# User Context (stable)")
        assert sb_idx < uc_idx

    def test_scope_boundary_absent_in_cold_start(self):
        stable, _ = _format_memory_context({}, _EMPTY_LEARNED)
        assert stable is not None
        assert "Scope Boundary" not in stable
        assert "Discovery Mode" in stable

    def test_scope_boundary_absent_when_only_untrusted(self):
        learned = {
            "learned_rules": [{"trigger": "t", "action": "a", "content": "x"}],
            "learned_preferences": [],
        }
        stable, untrusted = _format_memory_context({}, learned)
        assert stable is None
        assert untrusted is not None
        assert "Scope Boundary" not in untrusted

    def test_scope_boundary_with_mixed_stable_and_learned(self):
        ctx = {"global_profile": {"name": "Carol"}, "agent_instructions": [{"instruction": "Be verbose"}]}
        learned = {
            "learned_rules": [],
            "learned_preferences": [{"content": "user likes brief replies"}],
        }
        stable, untrusted = _format_memory_context(ctx, learned)
        assert stable is not None
        assert untrusted is not None
        assert "Scope Boundary" in stable
        assert "Scope Boundary" not in untrusted

    def test_scope_boundary_is_blockquote_format(self):
        ctx = {"global_profile": {"name": "Dave"}}
        stable, _ = _format_memory_context(ctx, _EMPTY_LEARNED)
        assert stable is not None
        assert "> **Scope Boundary**:" in stable


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
