"""Tests for unified pipeline builder and tool call grouping."""

from typing import cast

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.cache_policy import (
    resolve_cache_ttl_prune_policy,
)
from myrm_agent_harness.agent.context_management.infra.schemas import CacheTtlPruneConfig
from myrm_agent_harness.agent.context_management.pipeline import (
    build_default_processors,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor import (
    CacheTtlPruneProcessor,
)
from myrm_agent_harness.agent.context_management.strategies.tool_call_groups import (
    build_tool_call_groups,
)
from myrm_agent_harness.agent.middlewares.context_pipeline_helpers import (
    extract_compression_intent,
    extract_tool_names_and_schemas,
)


def test_build_default_processors_without_session_notes() -> None:
    processors = build_default_processors(max_context_tokens=32000)
    names = [processor.name for processor in processors]

    assert names == [
        "ThinkingBlockCleaner",
        "media_filter",
        "filter",
        "cache_ttl_prune",
        "compress",
        "summarize",
        "normalize",
        "media_resolver",
        "explicit_cache",
    ]


def test_resolve_cache_ttl_prune_policy_uses_model_family_profile() -> None:
    policy = resolve_cache_ttl_prune_policy("claude-3-5-sonnet")

    assert policy.model_family == "anthropic"
    assert policy.config.min_prunable_tokens == 8_000
    assert policy.config.hard_clear_ratio == 0.45
    assert policy.source_url == "https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching"


def test_resolve_cache_ttl_prune_policy_uses_provider_calibrated_ttl() -> None:
    openai_policy = resolve_cache_ttl_prune_policy("openai/gpt-4.1")
    google_policy = resolve_cache_ttl_prune_policy("google/gemini-2.5-pro")
    deepseek_policy = resolve_cache_ttl_prune_policy("deepseek-chat")

    assert openai_policy.config.ttl_seconds == 600.0
    assert google_policy.config.ttl_seconds == 3600.0
    assert deepseek_policy.config.ttl_seconds == 3600.0


def test_build_default_processors_shares_offload_with_cache_ttl_prune() -> None:
    async def offload(
        *,
        content: str,
        tool_name: str,
        scope_id: str | None,
    ) -> str:
        _ = content, tool_name, scope_id
        return ".context/test/tool.txt"

    processors = build_default_processors(
        max_context_tokens=32000,
        on_compress_offload=offload,
    )
    cache_prune = next(
        processor
        for processor in processors
        if isinstance(processor, CacheTtlPruneProcessor)
    )

    assert cache_prune._on_prune_offload is offload


def test_build_default_processors_accepts_cache_ttl_prune_config() -> None:
    config = CacheTtlPruneConfig(ttl_seconds=60)
    processors = build_default_processors(
        max_context_tokens=32000,
        cache_ttl_prune_config=config,
    )
    cache_prune = next(
        processor
        for processor in processors
        if isinstance(processor, CacheTtlPruneProcessor)
    )

    assert cache_prune._config is config


def test_build_default_processors_with_session_notes() -> None:
    processors = build_default_processors(
        max_context_tokens=32000,
        session_notes_manager=object(),  # type: ignore[arg-type]
    )
    names = [processor.name for processor in processors]

    assert names == [
        "ThinkingBlockCleaner",
        "media_filter",
        "filter",
        "cache_ttl_prune",
        "compress",
        "session_notes",
        "summarize",
        "normalize",
        "media_resolver",
        "explicit_cache",
    ]


def test_build_tool_call_groups_matches_by_tool_call_id() -> None:
    messages = [
        HumanMessage(content="query"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "read_file", "args": {"path": "a.py"}},
                {"id": "call_2", "name": "bash", "args": {"command": "pytest"}},
            ],
        ),
        ToolMessage(content="bash result", tool_call_id="call_2", name="bash"),
        ToolMessage(content="file result", tool_call_id="call_1", name="read_file"),
    ]

    groups = build_tool_call_groups(messages)

    assert [group.tool_call_id for group in groups] == ["call_1", "call_2"]
    assert groups[0].tool_index == 3
    assert groups[1].tool_index == 2


def test_build_tool_call_groups_skips_unmatched_tool_calls() -> None:
    messages = [
        HumanMessage(content="query"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "read_file", "args": {"path": "a.py"}},
                {"id": "call_2", "name": "bash", "args": {"command": "pytest"}},
            ],
        ),
        ToolMessage(content="only one result", tool_call_id="call_1", name="read_file"),
    ]

    groups = build_tool_call_groups(messages)

    assert len(groups) == 1
    assert groups[0].tool_call_id == "call_1"


def test_build_tool_call_groups_keeps_last_duplicate_tool_message() -> None:
    messages = [
        HumanMessage(content="query"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "bash", "args": {"command": "pytest"}}
            ],
        ),
        ToolMessage(content="stale result", tool_call_id="call_1", name="bash"),
        ToolMessage(content="latest result", tool_call_id="call_1", name="bash"),
    ]

    groups = build_tool_call_groups(messages)

    assert len(groups) == 1
    assert groups[0].tool_index == 3
    assert groups[0].tool_message.content == "latest result"


def test_build_tool_call_groups_handles_reused_tool_call_id_across_turns() -> None:
    messages = [
        HumanMessage(content="query"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "bash", "args": {"command": "pytest a"}}
            ],
        ),
        ToolMessage(content="result a", tool_call_id="call_1", name="bash"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "bash", "args": {"command": "pytest b"}}
            ],
        ),
        ToolMessage(content="result b", tool_call_id="call_1", name="bash"),
    ]

    groups = build_tool_call_groups(messages)

    assert len(groups) == 2
    assert groups[0].tool_index == 2
    assert groups[0].tool_message.content == "result a"
    assert groups[1].tool_index == 4
    assert groups[1].tool_message.content == "result b"


def test_extract_compression_intent_from_merged_context() -> None:
    intent = extract_compression_intent(
        {
            "compression_intent": {
                "focus_files": ["a.py"],
                "focus_modules": ["agent.context_management"],
                "failed_tool_call_ids": ["call_1"],
                "user_goal_hint": "fix compression",
            }
        }
    )

    assert intent == {
        "focus_files": ["a.py"],
        "focus_modules": ["agent.context_management"],
        "failed_tool_call_ids": ["call_1"],
        "user_goal_hint": "fix compression",
    }


class _UnstableRepr:
    def __repr__(self) -> str:
        return "<UnstableRepr at 0x1234>"


class _RequestWithTools:
    def __init__(self, tools: list[object]) -> None:
        self.tools = tools


def test_extract_tool_names_and_schemas_uses_stable_json() -> None:
    request = _RequestWithTools(
        [
            {
                "name": "unstable_tool",
                "description": "tool",
                "metadata": {"callback": _UnstableRepr()},
            }
        ]
    )

    result = extract_tool_names_and_schemas(cast(ModelRequest, request))

    assert result == [
        (
            "unstable_tool",
            '{"description": "tool", "metadata": {"callback": {"type": "_UnstableRepr"}}, "name": "unstable_tool"}',
        )
    ]
