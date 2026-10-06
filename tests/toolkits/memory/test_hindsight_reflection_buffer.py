# [POS] tests/toolkits/memory/test_hindsight_reflection_buffer.py
# [INPUT] FailureTurn, FailureTrajectoryScrubber, CounterfactualRuleExtractor, HindsightReflectionBuffer, HindsightRule, ReflectionBufferConfig
# [OUTPUT] pytest test suite for hindsight experience replay and reflection buffer

"""Unit and integration tests for Hindsight Experience Replay & Retrospective Reflection Buffer."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.hindsight import (
    CounterfactualRuleExtractor,
    FailureTrajectoryScrubber,
    FailureTurn,
    HindsightReflectionBuffer,
    HindsightRule,
    ReflectionBufferConfig,
)


def test_trajectory_scrubber_cleaning_and_turning_point() -> None:
    """Verify trajectory scrubbing, output truncation, and turning point location."""
    scrubber = FailureTrajectoryScrubber(max_output_chars=80)

    turns = [
        FailureTurn(
            turn_index=1,
            tool_name="web_search",
            tool_input={"query": "deploy docs"},
            tool_output="Found 10 relevant deployment guides." * 10,
            error_message="",
        ),
        FailureTurn(
            turn_index=2,
            tool_name="bash",
            tool_input={"command": "mkdir /restricted_root/site"},
            tool_output="mkdir: cannot create directory '/restricted_root/site': Permission denied",
            error_message="Exit code 1: Permission denied",
        ),
    ]

    cleaned_traj = scrubber.scrub(
        task_id="task-101",
        task_goal="Deploy internal portal to restricted root",
        turns=turns,
        terminal_error="Task aborted due to permission failure.",
        max_turns=5,
    )

    assert len(cleaned_traj.turns) == 2
    # Long output must be truncated
    assert len(cleaned_traj.turns[0].tool_output) <= 120
    assert "... [truncated] ..." in cleaned_traj.turns[0].tool_output

    # Turning point should be turn 2
    turning_point = scrubber.locate_turning_point(cleaned_traj)
    assert turning_point is not None
    assert turning_point.turn_index == 2
    assert turning_point.tool_name == "bash"


def test_counterfactual_rule_extractor() -> None:
    """Verify counterfactual rule extraction across different failure types."""
    extractor = CounterfactualRuleExtractor()
    scrubber = FailureTrajectoryScrubber()

    # 1. Permission Denied error
    perm_turns = [
        FailureTurn(
            turn_index=1,
            tool_name="bash",
            tool_input={"command": "chmod 777 /sys/firmware"},
            tool_output="Permission denied",
            error_message="Operation not permitted",
        )
    ]
    perm_traj = scrubber.scrub(
        "task-perm", "Adjust system firmware permissions", perm_turns, "Error"
    )
    rule_perm = extractor.extract_rule(perm_traj)
    assert "permission" in rule_perm.tags
    assert "Check file permissions" in rule_perm.correction_advice
    assert rule_perm.confidence >= 0.8

    # 2. File Not Found error
    not_found_turns = [
        FailureTurn(
            turn_index=1,
            tool_name="file_read",
            tool_input={"path": "/nonexistent/config.json"},
            tool_output="ENOENT: no such file or directory",
            error_message="File not found",
        )
    ]
    nf_traj = scrubber.scrub(
        "task-nf", "Read nonexistent config", not_found_turns, "Missing file"
    )
    rule_nf = extractor.extract_rule(nf_traj)
    assert "path" in rule_nf.tags
    assert "Verify target path" in rule_nf.correction_advice


def test_reflection_buffer_dedup_and_eviction() -> None:
    """Verify rule deduplication, reinforcement, and capacity limits."""
    config = ReflectionBufferConfig(max_capacity=2, min_confidence=0.5)
    buffer = HindsightReflectionBuffer(config)

    rule1 = HindsightRule(
        rule_id="r1",
        task_pattern="[bash] install packages",
        mistake_signature="Missing -y flag in non-interactive apt-get",
        correction_advice="Always pass -y flag to apt-get in automated scripts",
        tags=["bash", "apt"],
        confidence=0.8,
        hit_count=1,
    )
    rule2 = HindsightRule(
        rule_id="r2",
        task_pattern="[docker] run container",
        mistake_signature="Port collision on 8080",
        correction_advice="Check port availability before running container",
        tags=["docker", "port"],
        confidence=0.85,
        hit_count=2,
    )

    buffer.record_rule(rule1)
    buffer.record_rule(rule2)
    assert len(buffer.get_all_rules()) == 2

    # Reinforce rule1 with identical pattern
    reinforced = buffer.record_rule(
        HindsightRule(
            rule_id="r1-new",
            task_pattern="[bash] install packages",
            mistake_signature="Missing -y flag in non-interactive apt-get",
            correction_advice="Always pass -y flag to apt-get in automated scripts",
            tags=["bash", "debian"],
            confidence=0.8,
            hit_count=1,
        )
    )
    # Total distinct rules still 2, but hit count incremented
    assert len(buffer.get_all_rules()) == 2
    assert reinforced.hit_count == 2
    assert reinforced.confidence >= 0.85
    assert "debian" in reinforced.tags

    # Add 3rd rule -> triggers eviction of lowest (hit_count, confidence)
    rule3 = HindsightRule(
        rule_id="r3",
        task_pattern="[git] commit",
        mistake_signature="Empty commit without changes",
        correction_advice="Check git status before commit",
        tags=["git"],
        confidence=0.9,
        hit_count=3,
    )
    buffer.record_rule(rule3)
    assert len(buffer.get_all_rules()) == 2


def test_end_to_end_hindsight_pre_execution_guard() -> None:
    """End-to-end test: failure occurs -> hindsight extracts rule -> subsequent task is warned."""
    scrubber = FailureTrajectoryScrubber()
    extractor = CounterfactualRuleExtractor()
    buffer = HindsightReflectionBuffer()

    # Step 1: Task 1 encounters a failure due to non-interactive prompt deadlock
    failed_turns = [
        FailureTurn(
            turn_index=1,
            tool_name="bash",
            tool_input={"command": "npm init"},
            tool_output="Hang timeout waiting for user package name input...",
            error_message="Command timed out after 30000ms",
        )
    ]
    trajectory = scrubber.scrub(
        task_id="task-init-01",
        task_goal="Initialize modern node.js project with npm init",
        turns=failed_turns,
        terminal_error="CLI hung waiting for stdin input",
    )

    # Step 2: Hindsight counterfactual reflection extracts actionable rule
    hindsight_rule = extractor.extract_rule(trajectory)
    buffer.record_rule(hindsight_rule)

    stats = buffer.get_stats()
    assert stats["total_rules"] == 1

    # Step 3: New Task 2 arrives with similar execution intent
    new_task_goal = "Initialize new npm project repository using bash"
    warnings = buffer.match_warnings(
        task_goal=new_task_goal,
        intended_tools=["bash"],
        top_k=2,
    )

    # Step 4: Proactive warning successfully matches and advises the Agent
    assert len(warnings) == 1
    w = warnings[0]
    assert w.rule_id == hindsight_rule.rule_id
    assert "timeout" in w.warning_text.lower() or "hung" in w.warning_text.lower()
    assert "recommended pre-action" in w.recommended_action.lower()
