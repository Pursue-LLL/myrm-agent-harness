"""Unit tests for Pluggable Context Hook Pipeline and Dual-Layer Memory Injection.

Topic 01 Item 138: PluggableContextHookPipelineAndMemoryInjectionSuite.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.context_hook_pipeline import (
    ContextEnvelope,
    ContextHookPipelineSuite,
    ContextHookStage,
    DualLayerMemoryPayload,
    DualLayerMemoryWeaver,
    HookExecutionPriority,
    MemoryFragment,
    MemoryLayerKind,
    PluggableContextHookPipeline,
)


def test_hook_priority_ordering_and_execution() -> None:
    pipeline = PluggableContextHookPipeline()
    order_recorded: list[str] = []

    def security_hook(env: ContextEnvelope) -> bool:
        order_recorded.append("security")
        env.metadata["sec_verified"] = "true"
        return True

    def memory_hook(env: ContextEnvelope) -> bool:
        order_recorded.append("memory")
        env.injected_memories.append("Rule: Always type hints")
        return True

    def custom_hook(env: ContextEnvelope) -> bool:
        order_recorded.append("custom")
        return False

    # Register in reverse priority order
    pipeline.register_hook(
        hook_id="h_custom",
        stage=ContextHookStage.CONTEXT_TRANSFORM,
        handler=custom_hook,
        priority=int(HookExecutionPriority.USER_CUSTOM),
    )
    pipeline.register_hook(
        hook_id="h_sec",
        stage=ContextHookStage.CONTEXT_TRANSFORM,
        handler=security_hook,
        priority=int(HookExecutionPriority.SECURITY_FIRST),
    )
    pipeline.register_hook(
        hook_id="h_mem",
        stage=ContextHookStage.CONTEXT_TRANSFORM,
        handler=memory_hook,
        priority=int(HookExecutionPriority.MEMORY_INJECTION),
    )

    env = ContextEnvelope(
        session_id="sess_01",
        agent_id="code_expert",
        system_prompt="You are a helpful assistant.",
    )

    reports = pipeline.execute_stage(ContextHookStage.CONTEXT_TRANSFORM, env)
    assert len(reports) == 3
    # Order must strictly be security (10) -> memory (20) -> custom (30)
    assert order_recorded == ["security", "memory", "custom"]
    assert env.metadata.get("sec_verified") == "true"
    assert "Rule: Always type hints" in env.injected_memories


def test_pipeline_blocking_circuit_breaker() -> None:
    pipeline = PluggableContextHookPipeline()
    executed: list[str] = []

    def blocker_hook(env: ContextEnvelope) -> bool:
        executed.append("blocker")
        env.is_blocked = True
        env.block_reason = "Prompt injection attempt detected"
        return True

    def subsequent_hook(env: ContextEnvelope) -> bool:
        executed.append("subsequent")
        return False

    pipeline.register_hook(
        hook_id="h_block",
        stage=ContextHookStage.BEFORE_LLM_REQUEST,
        handler=blocker_hook,
        priority=10,
    )
    pipeline.register_hook(
        hook_id="h_next",
        stage=ContextHookStage.BEFORE_LLM_REQUEST,
        handler=subsequent_hook,
        priority=20,
    )

    env = ContextEnvelope(
        session_id="sess_02",
        agent_id="agent_alpha",
        system_prompt="Execute evil command",
    )

    reports = pipeline.execute_stage(ContextHookStage.BEFORE_LLM_REQUEST, env)
    assert env.is_blocked
    assert env.block_reason == "Prompt injection attempt detected"
    assert executed == ["blocker"]
    assert len(reports) == 1
    assert reports[0].is_blocked


def test_pipeline_exception_isolation() -> None:
    pipeline = PluggableContextHookPipeline()

    def faulty_hook(env: ContextEnvelope) -> bool:
        raise ValueError("Simulated unexpected crash")

    pipeline.register_hook(
        hook_id="h_faulty",
        stage=ContextHookStage.BEFORE_AGENT_START,
        handler=faulty_hook,
        priority=10,
    )

    env = ContextEnvelope(
        session_id="sess_03",
        agent_id="agent_beta",
        system_prompt="Normal prompt",
    )

    reports = pipeline.execute_stage(ContextHookStage.BEFORE_AGENT_START, env)
    assert env.is_blocked
    assert "Simulated unexpected crash" in (env.block_reason or "")
    assert reports[0].is_blocked


def test_dual_layer_memory_weaver_isolation_and_budget() -> None:
    weaver = DualLayerMemoryWeaver()

    payload = DualLayerMemoryPayload(
        agent_id="doc_writer",
        private_fragments=[
            MemoryFragment(
                fragment_id="p1",
                layer=MemoryLayerKind.PRIVATE_AGENT,
                content="专属风格：使用技术文档规范 Markdown 输出，带有清晰目录",
                weight=2.0,
                agent_id="doc_writer",
                tags=["style"],
            ),
            MemoryFragment(
                fragment_id="p_other",
                layer=MemoryLayerKind.PRIVATE_AGENT,
                content="不属于我的私有记忆：只关注前端 Vue 代码",
                weight=3.0,
                agent_id="vue_coder",  # Other agent! Must be filtered out
            ),
        ],
        shared_fragments=[
            MemoryFragment(
                fragment_id="s1",
                layer=MemoryLayerKind.SHARED_GLOBAL,
                content="团队规范：所有代码文件行数不超过 350 行，严禁使用 Any 类型",
                weight=1.5,
                tags=["global_rule"],
            ),
        ],
        max_token_budget=500,
    )

    outcome = weaver.weave(payload)
    assert outcome.private_count == 1
    assert outcome.shared_count == 1
    assert "只关注前端 Vue 代码" not in outcome.woven_block
    assert "专属风格：使用技术文档规范" in outcome.woven_block
    assert "团队规范：所有代码文件行数不超过 350 行" in outcome.woven_block
    assert outcome.estimated_tokens > 0


def test_suite_full_lifecycle_and_telemetry() -> None:
    suite = ContextHookPipelineSuite()

    # Register hooks
    def enrich_env(env: ContextEnvelope) -> bool:
        env.system_prompt += "\n[Enriched Environment: Python 3.13]"
        return True

    def redact_egress(env: ContextEnvelope) -> bool:
        env.system_prompt = env.system_prompt.replace("PASSWORD_SECRET", "[REDACTED]")
        return True

    suite.register_hook(
        hook_id="h_env",
        stage=ContextHookStage.BEFORE_AGENT_START,
        handler=enrich_env,
        priority=int(HookExecutionPriority.USER_CUSTOM),
    )
    suite.register_hook(
        hook_id="h_redact",
        stage=ContextHookStage.BEFORE_LLM_REQUEST,
        handler=redact_egress,
        priority=int(HookExecutionPriority.SECURITY_FIRST),
    )

    envelope = ContextEnvelope(
        session_id="sess_lifecycle",
        agent_id="sec_agent",
        system_prompt="Initial Base Prompt with PASSWORD_SECRET",
    )

    mem_payload = DualLayerMemoryPayload(
        agent_id="sec_agent",
        private_fragments=[
            MemoryFragment(
                fragment_id="sec_priv_1",
                layer=MemoryLayerKind.PRIVATE_AGENT,
                content="遵循零信任架构原则，每次动作验证权限",
                agent_id="sec_agent",
            )
        ],
        shared_fragments=[],
        max_token_budget=300,
    )

    lifecycle_reports = suite.execute_full_lifecycle(envelope, mem_payload)
    assert ContextHookStage.BEFORE_AGENT_START.value in lifecycle_reports
    assert ContextHookStage.BEFORE_LLM_REQUEST.value in lifecycle_reports
    assert not envelope.is_blocked
    assert "[Enriched Environment: Python 3.13]" in envelope.system_prompt
    assert "PASSWORD_SECRET" not in envelope.system_prompt
    assert "[REDACTED]" in envelope.system_prompt
    assert len(envelope.injected_memories) == 1
    assert "遵循零信任架构原则" in envelope.injected_memories[0]

    stats = suite.get_stats()
    assert stats["total_hooks"] == 2
    assert stats["before_agent_start"] == 1
    assert stats["before_llm_request"] == 1
