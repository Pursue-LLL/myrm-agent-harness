"""Unit tests for Approval False Positive Metric Loop suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.approval_metrics import (
    ApprovalMetricCollector,
    ClassifierDecision,
    FeedbackOutcome,
)


def test_record_and_retrieve_verdict() -> None:
    collector = ApprovalMetricCollector()
    entry = collector.record_verdict(
        command="npm install lodash",
        decision=ClassifierDecision.ALLOW,
        reason="Package declared in package.json manifest",
        workspace_root="/workspace/web",
        taint_labels=["SAFE_BUILD"],
        timestamp=1000.0,
        audit_id="audit-001",
    )

    assert entry.audit_id == "audit-001"
    assert entry.decision == ClassifierDecision.ALLOW
    assert entry.feedback == FeedbackOutcome.UNREVIEWED

    retrieved = collector.get_verdict("audit-001")
    assert retrieved is not None
    assert retrieved.command == "npm install lodash"
    assert retrieved.taint_labels == ["SAFE_BUILD"]


def test_submit_feedback_and_fpr_calculation() -> None:
    collector = ApprovalMetricCollector(default_alert_threshold=0.10)
    now = 1000.0

    # 1. Action 1: ALLOW (safe action)
    collector.record_verdict(
        command="cat README.md",
        decision=ClassifierDecision.ALLOW,
        reason="Read-only file read",
        timestamp=now - 50.0,
        audit_id="aud-1",
    )

    # 2. Action 2: DENY (true positive - malicious rm)
    collector.record_verdict(
        command="rm -rf / --no-preserve-root",
        decision=ClassifierDecision.DENY,
        reason="Destroy exfiltrate root rule",
        timestamp=now - 40.0,
        audit_id="aud-2",
    )
    collector.submit_feedback(
        audit_id="aud-2",
        feedback=FeedbackOutcome.TRUE_POSITIVE,
        feedback_reason="Malicious destructive command confirmed",
        reviewed_at=now - 35.0,
    )

    # 3. Action 3: DENY (false positive - legitimate build script blocked)
    collector.record_verdict(
        command="bash ./scripts/clean_build_cache.sh",
        decision=ClassifierDecision.DENY,
        reason="Destructive command pattern detected",
        timestamp=now - 30.0,
        audit_id="aud-3",
    )
    collector.submit_feedback(
        audit_id="aud-3",
        feedback=FeedbackOutcome.FALSE_POSITIVE,
        feedback_reason="Legitimate internal build script overturned by developer",
        reviewed_at=now - 25.0,
    )

    # 4. Action 4: UNCERTAIN (false positive - ask overturned by user)
    collector.record_verdict(
        command="git checkout -b feature/login",
        decision=ClassifierDecision.UNCERTAIN,
        reason="Ambiguous user intent",
        timestamp=now - 20.0,
        audit_id="aud-4",
    )
    collector.submit_feedback(
        audit_id="aud-4",
        feedback=FeedbackOutcome.CONFIRMED_SAFE,
        feedback_reason="Standard branch creation matching user request",
        reviewed_at=now - 15.0,
    )

    # Calculate metrics
    metrics = collector.calculate_metrics(
        window_seconds=3600.0,
        alert_threshold=0.15,
        current_time=now,
    )

    # Total evaluations = 4
    assert metrics.total_evaluations == 4
    # Blocks or asks (DENY + UNCERTAIN) = 3 (aud-2, aud-3, aud-4)
    assert metrics.total_blocks_or_asks == 3
    # Confirmed false positives = 2 (aud-3 + aud-4)
    assert metrics.confirmed_false_positives == 2
    # Confirmed true positives = 1 (aud-2)
    assert metrics.confirmed_true_positives == 1
    # FPR = 2 / 3 = 0.6667
    assert metrics.false_positive_rate == 0.6667
    # FPR (0.6667) > alert_threshold (0.15) -> alerting
    assert metrics.is_alerting is True


def test_export_false_positive_samples_and_rule_tuning() -> None:
    collector = ApprovalMetricCollector()
    now = 1000.0

    collector.record_verdict(
        command="docker build -t app:latest .",
        decision=ClassifierDecision.DENY,
        reason="Docker socket interaction without review",
        timestamp=now - 10.0,
        audit_id="aud-docker",
    )
    collector.submit_feedback(
        audit_id="aud-docker",
        feedback=FeedbackOutcome.FALSE_POSITIVE,
        feedback_reason="Routine local container build requested in prompt",
        reviewed_at=now - 5.0,
    )

    samples = collector.export_false_positive_samples(limit=10)
    assert len(samples) == 1
    sample = samples[0]
    assert sample.audit_id == "aud-docker"
    assert sample.command == "docker build -t app:latest ."
    assert sample.decision == ClassifierDecision.DENY
    assert "Add command pattern 'docker build" in sample.suggested_rule_tuning
    assert "ALLOW EXCEPTIONS" in sample.suggested_rule_tuning


def test_sliding_window_filtering() -> None:
    collector = ApprovalMetricCollector()
    now = 2000.0

    # Old event (outside 1h window)
    collector.record_verdict(
        command="old cmd",
        decision=ClassifierDecision.DENY,
        reason="old reason",
        timestamp=now - 5000.0,
        audit_id="old-aud",
    )
    collector.submit_feedback(
        audit_id="old-aud",
        feedback=FeedbackOutcome.FALSE_POSITIVE,
        feedback_reason="old fp",
    )

    # Recent event (inside 1h window)
    collector.record_verdict(
        command="new cmd",
        decision=ClassifierDecision.ALLOW,
        reason="new reason",
        timestamp=now - 100.0,
        audit_id="new-aud",
    )

    metrics = collector.calculate_metrics(
        window_seconds=3600.0,
        current_time=now,
    )
    assert metrics.total_evaluations == 1
    assert metrics.total_blocks_or_asks == 0
    assert metrics.confirmed_false_positives == 0
    assert metrics.false_positive_rate == 0.0
    assert metrics.is_alerting is False
