# [POS]: tests.unit.toolkits.memory.test_idle_and_budget_gated_auto_memory_engine_suite
# [INPUT]: myrm_agent_harness.toolkits.memory.auto_consolidation
# [OUTPUT]: TestIdleAndBudgetGatedAutoMemoryEngineSuite

"""Unit tests for Idle & Budget Gated Auto-Memory Engine Suite (Item 123 P1).

Verifies:
1. Session idle timeout detection accuracy.
2. Turn gate rejecting short conversations (< 3 turns).
3. Information gain density gate rejecting trivial chit-chat.
4. Token budget gate protecting depleted reserves & ratio bounds.
5. Six-dimensional structured memory extraction fidelity.
6. Orchestration facade end-to-end admission and consolidation execution.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.auto_consolidation.gating_engine import (
    calculate_information_density,
    evaluate_budget_safety,
    evaluate_idle_status,
    evaluate_turn_and_info_gain,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.models import (
    AutoMemoryGatingConfig,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.orchestrator import (
    AutoMemoryConsolidationOrchestrator,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.six_dimensional_extractor import (
    SixDimensionalMemoryExtractor,
)
from myrm_agent_harness.toolkits.memory.auto_memory import (
    AutoMemoryBudgetPolicy,
    AutoMemoryGatingDecision,
    IdleAndBudgetGatedAutoMemoryEngine,
    SessionActivitySnapshot,
)


class TestIdleAndBudgetGatedAutoMemoryEngineSuite:
    """Test suite for Item 123 idle and budget gated auto-consolidation engine."""

    def test_idle_detection_timing(self) -> None:
        """Verify idle evaluation triggers only when elapsed inactivity exceeds threshold."""
        config = AutoMemoryGatingConfig(idle_timeout_seconds=600.0)
        base_time = 1000.0

        # Case 1: Inactive for only 300s (below 600s threshold)
        active_state = evaluate_idle_status(
            session_id="sess-01",
            last_active_timestamp=base_time,
            current_timestamp=base_time + 300.0,
            config=config,
        )
        assert not active_state.is_idle_triggered
        assert active_state.idle_seconds == 300.0
        assert "below idle threshold" in active_state.reason

        # Case 2: Inactive for 650s (exceeds threshold)
        idle_state = evaluate_idle_status(
            session_id="sess-01",
            last_active_timestamp=base_time,
            current_timestamp=base_time + 650.0,
            config=config,
        )
        assert idle_state.is_idle_triggered
        assert idle_state.idle_seconds == 650.0
        assert "Background consolidation eligible" in idle_state.reason

    def test_turn_gate_short_conversation_rejection(self) -> None:
        """Verify conversations with fewer than minimum turns are rejected."""
        config = AutoMemoryGatingConfig(min_turn_count=3)
        short_messages = [
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "Paris is the capital of France."},
        ]

        decision = evaluate_turn_and_info_gain(short_messages, config=config)
        assert not decision.passed
        assert decision.turn_count == 1
        assert "Conversation too brief" in decision.reason

    def test_turn_gate_trivial_chitchat_rejection(self) -> None:
        """Verify conversations with trivial chit-chat fail the info-density gate."""
        config = AutoMemoryGatingConfig(min_turn_count=3, min_info_density=0.35)
        trivial_messages = [
            {"role": "user", "content": "Hi there"},
            {"role": "assistant", "content": "Hello! How can I help?"},
            {"role": "user", "content": "Ok thanks"},
            {"role": "assistant", "content": "You are welcome!"},
            {"role": "user", "content": "好的 谢谢你"},
            {"role": "assistant", "content": "不客气"},
        ]

        density = calculate_information_density(trivial_messages)
        decision = evaluate_turn_and_info_gain(trivial_messages, config=config)
        assert density < 0.35
        assert not decision.passed
        assert "Information density too low" in decision.reason

    def test_budget_gate_depleted_and_cost_ratio(self) -> None:
        """Verify token budget protection gate enforces safety floors and cost ratios."""
        config = AutoMemoryGatingConfig(
            min_remaining_budget_tokens=1000,
            max_consolidation_cost_ratio=0.20,
        )
        messages = [
            {"role": "user", "content": "Refactor database migrations to use SQLite with strict concurrency checks."},
            {"role": "assistant", "content": "Implemented WAL mode and connection pooling to avoid locking errors."},
            {"role": "user", "content": "Ensure zero Any types and add complete type hints throughout."},
            {"role": "assistant", "content": "All models annotated with strict TypedDict and Pydantic schemas."},
        ]

        # Case 1: Depleted balance (800 < 1000 floor)
        decision_depleted = evaluate_budget_safety(
            remaining_tokens=800,
            messages=messages,
            config=config,
        )
        assert not decision_depleted.passed
        assert "budget depleted/critical" in decision_depleted.reason

        # Case 2: Excessive cost ratio (estimated cost ~800 tokens, remaining 2000 -> ratio ~40% > 20%)
        decision_ratio_exceeded = evaluate_budget_safety(
            remaining_tokens=2000,
            messages=messages,
            config=config,
        )
        assert not decision_ratio_exceeded.passed
        assert "cost ratio" in decision_ratio_exceeded.reason

        # Case 3: Healthy balance (20000 tokens remaining)
        decision_healthy = evaluate_budget_safety(
            remaining_tokens=20000,
            messages=messages,
            config=config,
        )
        assert decision_healthy.passed
        assert decision_healthy.cost_ratio < 0.20

    def test_six_dimensional_extractor_dimensions(self) -> None:
        """Verify SixDimensionalMemoryExtractor yields all 6 required structured dimensions."""
        extractor = SixDimensionalMemoryExtractor()
        messages = [
            {
                "role": "user",
                "content": "In our project, we always require strict type hints and never allow Any types.",
            },
            {
                "role": "assistant",
                "content": "Understood. We will implement clean architecture pattern with decoupled storage.",
            },
            {
                "role": "user",
                "content": "We encountered an error with SQLite database locks when concurrent workers write.",
            },
            {
                "role": "assistant",
                "content": "The bug was resolved by enabling WAL journal mode and setting timeout=30.",
            },
        ]
        tool_records = ["run_command", "view_file", "run_command", "replace_file_content"]

        artifact = extractor.extract(
            session_id="sess-proj-x",
            messages=messages,
            working_directory="/home/developer/app",
            tool_call_records=tool_records,
            token_cost=520,
        )

        assert artifact.session_id == "sess-proj-x"
        assert artifact.working_directory == "/home/developer/app"
        assert artifact.token_cost == 520
        assert len(artifact.key_topics) >= 1
        assert len(artifact.user_preferences) >= 1
        assert any("strict type hints" in pref for pref in artifact.user_preferences)
        assert len(artifact.failure_lessons) >= 1
        assert any("error" in lesson.lower() or "sqlite" in lesson.lower() for lesson in artifact.failure_lessons)
        assert len(artifact.tool_calling_patterns) >= 1
        assert any("run_command" in p for p in artifact.tool_calling_patterns)
        assert "Workspace: /home/developer/app" in artifact.summary_digest

    def test_orchestrator_end_to_end_admission_and_bypass(self) -> None:
        """Verify orchestrator gates execution and respects force_bypass_gating."""
        config = AutoMemoryGatingConfig(
            idle_timeout_seconds=300.0,
            min_turn_count=2,
            min_info_density=0.2,
            min_remaining_budget_tokens=500,
        )
        orchestrator = AutoMemoryConsolidationOrchestrator(config=config)
        messages = [
            {"role": "user", "content": "Set up clean architecture repository layout for the payment microservice."},
            {"role": "assistant", "content": "Created domain, ports, adapters, and infrastructure directories."},
        ]

        # 1. Gate evaluation when NOT idle (last active just now)
        report_not_idle = orchestrator.evaluate_session_gating(
            session_id="sess-orch-1",
            messages=messages,
            remaining_tokens=10000,
            last_active_timestamp=1000.0,
            current_timestamp=1050.0,
            require_idle=True,
        )
        assert not report_not_idle.should_consolidate

        # 2. Run consolidation when NOT idle -> bypassed (returns None artifact)
        rep, art = orchestrator.consolidate_session(
            session_id="sess-orch-1",
            messages=messages,
            remaining_tokens=10000,
            working_directory="/workspace/microservice",
            last_active_timestamp=1000.0,
            current_timestamp=1050.0,
            require_idle=True,
        )
        assert not rep.should_consolidate
        assert art is None

        # 3. Run consolidation with force_bypass_gating=True -> produces artifact
        rep_forced, art_forced = orchestrator.consolidate_session(
            session_id="sess-orch-1",
            messages=messages,
            remaining_tokens=10000,
            working_directory="/workspace/microservice",
            last_active_timestamp=1000.0,
            current_timestamp=1050.0,
            force_bypass_gating=True,
            require_idle=True,
        )
        assert not rep_forced.should_consolidate
        assert art_forced is not None
        assert art_forced.working_directory == "/workspace/microservice"

    def test_auto_memory_engine_and_gate_pipeline(self) -> None:
        """Verify IdleAndBudgetGatedAutoMemoryEngine end-to-end gating and 6D extraction."""
        engine = IdleAndBudgetGatedAutoMemoryEngine()
        policy = AutoMemoryBudgetPolicy(
            min_turns_threshold=3,
            idle_timeout_seconds=600.0,
            max_token_budget_ceiling=50000,
        )

        # Case 1: Short turns conversation (< 3 turns)
        snap_short = SessionActivitySnapshot(
            session_id="s1",
            last_active_at_timestamp=100.0,
            turn_count=1,
            total_tokens_consumed=500,
            workspace_path="/workspace/proj",
        )
        res_short = engine.process_session(
            snapshot=snap_short,
            messages=[{"role": "user", "content": "hello"}],
            policy=policy,
            now_ts=800.0,
        )
        assert not res_short.is_eligible
        assert res_short.decision == AutoMemoryGatingDecision.SKIPPED_SHORT_CONVERSATION

        # Case 2: Sufficient turns but NOT idle
        snap_active = SessionActivitySnapshot(
            session_id="s2",
            last_active_at_timestamp=750.0,
            turn_count=4,
            total_tokens_consumed=1500,
            workspace_path="/workspace/proj",
        )
        res_active = engine.process_session(
            snapshot=snap_active,
            messages=[
                {"role": "user", "content": "架构设计要求必须使用 Python 类型注解规范。"},
                {"role": "assistant", "content": "收到，严格遵循 PEP8 且严禁使用 any 类型。"},
                {"role": "user", "content": "排查刚才的连接错误 exception bug 并完成修复。"},
                {"role": "assistant", "content": "```python\ndef solve(): pass\n```\n已修复连接异常。"},
            ],
            policy=policy,
            now_ts=800.0,  # only 50s elapsed < 600s
        )
        assert not res_active.is_eligible
        assert res_active.decision == AutoMemoryGatingDecision.SKIPPED_NOT_IDLE

        # Case 3: Fully eligible (idle > 600s, turns >= 3, budget healthy) -> 6D slice generated
        snap_eligible = SessionActivitySnapshot(
            session_id="s3",
            last_active_at_timestamp=100.0,
            turn_count=4,
            total_tokens_consumed=2000,
            workspace_path="/workspace/proj",
        )
        messages_rich = [
            {"role": "user", "content": "架构设计要求必须使用 Python 类型注解规范，严禁使用 any 类型。"},
            {"role": "assistant", "content": "```python\ndef solve(): pass\n```\n完全遵循该规范。"},
            {"role": "user", "content": "请记录排查刚才的连接错误与数据库超时 exception 的避坑教训。"},
            {"role": "assistant", "content": "已分析原因：连接池枯竭，增加自动重试与超时重连修复方案。"},
        ]
        res_eligible = engine.process_session(
            snapshot=snap_eligible,
            messages=messages_rich,
            policy=policy,
            now_ts=800.0,  # 700s elapsed >= 600s
        )
        assert res_eligible.is_eligible
        assert res_eligible.decision == AutoMemoryGatingDecision.ACCEPTED
        assert res_eligible.memory_slice is not None

        slice_data = res_eligible.memory_slice
        assert slice_data.workspace_env == "/workspace/proj"
        assert len(slice_data.user_preferences) > 0
        assert len(slice_data.reusable_knowledge) > 0
        assert len(slice_data.failure_lessons) > 0

