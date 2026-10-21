"""[INPUT] External event triggers, causality rules, agent decision nodes, and file artifact diffs.
[OUTPUT] Unit tests verifying end-to-end causality lineage DAG and reverse file change attribution.
[POS] myrm-agent-harness/tests/observability/test_event_causality_lineage.py
"""

from myrm_agent_harness.observability.event_causality_lineage import (
    AgentActionNode,
    ArtifactChangeRecord,
    CausalityLineageRecord,
    CausalityRuleMatch,
    EventCausalityTracker,
    ExternalEventTrigger,
    FileAttributionResult,
)


def _build_sample_lineage(trace_id: str = "cau_001", file_target: str = "src/auth/service.py") -> tuple[
    ExternalEventTrigger,
    CausalityRuleMatch,
    list[AgentActionNode],
    list[ArtifactChangeRecord],
]:
    trigger = ExternalEventTrigger(
        event_id="gh_issue_104",
        source_type="github_webhook",
        event_name="issues.opened",
        payload_summary="P0 Security vulnerability: token leak in session refresh",
    )
    rule = CausalityRuleMatch(
        rule_id="rule_auto_patch_p0",
        rule_name="P0 缺陷自动修补流水线",
        matched_condition="severity == 'P0' and labels.contains('security')",
    )
    actions = [
        AgentActionNode(
            action_id="act_01",
            agent_role="Security Auditor",
            decision_rationale="定位到 refresh_token 未进行哈希加盐处理",
            tool_name="code_search",
            input_summary="search refresh_token in auth/service.py",
            duration_ms=420.0,
            tokens_consumed=1250,
        ),
        AgentActionNode(
            action_id="act_02",
            agent_role="Python Refactoring Specialist",
            decision_rationale="引入 HMAC-SHA256 签名校验并修复内存脱敏",
            tool_name="replace_file_content",
            input_summary="patch auth/service.py with secure hash routine",
            duration_ms=850.0,
            tokens_consumed=1800,
        ),
    ]
    artifacts = [
        ArtifactChangeRecord(
            file_path=file_target,
            change_type="modified",
            diff_summary="+ def secure_hash_token(raw_token: str) -> str:",
            commit_sha="a1b2c3d4e5f6",
        ),
    ]
    return trigger, rule, actions, artifacts


def test_record_causality_lineage_and_dag_structure() -> None:
    """Verifies that an end-to-end causality DAG is correctly recorded and aggregated."""
    tracker = EventCausalityTracker()
    trigger, rule, actions, artifacts = _build_sample_lineage()

    record: CausalityLineageRecord = tracker.record_lineage(
        causality_trace_id="cau_trace_101",
        session_id="sess_sec_auto_fix",
        trigger=trigger,
        rule=rule,
        agent_role="Python Refactoring Specialist",
        actions=actions,
        artifacts=artifacts,
    )

    assert record.causality_trace_id == "cau_trace_101"
    assert record.trigger.event_id == "gh_issue_104"
    assert record.rule.rule_id == "rule_auto_patch_p0"
    assert len(record.actions) == 2
    assert len(record.artifacts) == 1
    # 1250 + 1800 = 3050 tokens
    assert record.total_tokens == 3050
    # 420.0 + 850.0 = 1270.0 ms
    assert abs(record.total_duration_ms - 1270.0) < 1e-4

    fetched = tracker.get_lineage("cau_trace_101")
    assert fetched is not None
    assert fetched.agent_role == "Python Refactoring Specialist"


def test_reverse_file_change_attribution() -> None:
    """Verifies 1-second reverse file lookup resolving a changed file back to its external trigger."""
    tracker = EventCausalityTracker()
    trigger, rule, actions, artifacts = _build_sample_lineage(file_target="src/auth/service.py")

    tracker.record_lineage(
        causality_trace_id="cau_trace_202",
        session_id="sess_sec_02",
        trigger=trigger,
        rule=rule,
        agent_role="Python Refactoring Specialist",
        actions=actions,
        artifacts=artifacts,
    )

    # Reverse lookup by file path
    attributions: list[FileAttributionResult] = tracker.reverse_lookup_file("src/auth/service.py")
    assert len(attributions) == 1

    attr = attributions[0]
    assert attr.file_path == "src/auth/service.py"
    assert attr.trigger_event_id == "gh_issue_104"
    assert attr.source_type == "github_webhook"
    assert attr.agent_role == "Python Refactoring Specialist"
    assert "引入 HMAC-SHA256" in attr.rationale
    assert attr.change_record.commit_sha == "a1b2c3d4e5f6"

    # Non-existent file lookup
    empty_results = tracker.reverse_lookup_file("src/unrelated/other.py")
    assert len(empty_results) == 0


def test_lineage_filtering_by_source_and_event() -> None:
    """Verifies querying lineages with source_type and event_id filters."""
    tracker = EventCausalityTracker()
    trigger, rule, actions, artifacts = _build_sample_lineage()

    tracker.record_lineage(
        causality_trace_id="cau_trace_gh",
        session_id="sess_gh",
        trigger=trigger,
        rule=rule,
        agent_role="Bot",
        actions=actions,
        artifacts=artifacts,
    )

    # Query with matching filter
    gh_items = tracker.list_lineages(source_type="github_webhook")
    assert len(gh_items) == 1
    assert gh_items[0].causality_trace_id == "cau_trace_gh"

    # Query with non-matching filter
    slack_items = tracker.list_lineages(source_type="slack_mention")
    assert len(slack_items) == 0


def test_tracker_reset() -> None:
    """Verifies that reset clears all recorded lineages and reverse indexes."""
    tracker = EventCausalityTracker()
    trigger, rule, actions, artifacts = _build_sample_lineage()

    tracker.record_lineage(
        causality_trace_id="cau_tmp",
        session_id="sess_tmp",
        trigger=trigger,
        rule=rule,
        agent_role="Bot",
        actions=actions,
        artifacts=artifacts,
    )

    assert len(tracker.list_lineages()) == 1
    assert len(tracker.reverse_lookup_file("src/auth/service.py")) == 1

    tracker.reset()
    assert len(tracker.list_lineages()) == 0
    assert len(tracker.reverse_lookup_file("src/auth/service.py")) == 0
