"""Unit tests for Cross-Collaborator 'Big @' Session Reference & Context Borrowing Bridge (Item 32)."""

from myrm_agent_harness.runtime.context.big_at_context_bridge import (
    BigAtReference,
    BigAtSyntaxParser,
    BigAtTargetKind,
    ContextBorrowingBridge,
    ContextBorrowingConfig,
    DistilledSessionContext,
    ZeroExplanationContextExtractor,
)
from myrm_agent_harness.utils.text_utils import get_token_count


def test_big_at_syntax_parsing() -> None:
    """Verifies scanning and extraction of canonical and shorthand 'Big @' tokens."""
    prompt = (
        "Please check @session:sess_core_100 and @collab:alice/ui_revamp as well as "
        "@agent:codex/perf_bench and shorthand @bob/db_migration to fix the issue."
    )

    refs: list[BigAtReference] = BigAtSyntaxParser.parse_references(prompt)

    assert len(refs) == 4

    # 1. @session:sess_core_100
    assert refs[0].target_kind == BigAtTargetKind.SESSION
    assert refs[0].primary_identifier == "sess_core_100"
    assert refs[0].secondary_identifier is None

    # 2. @collab:alice/ui_revamp
    assert refs[1].target_kind == BigAtTargetKind.COLLABORATOR
    assert refs[1].primary_identifier == "alice"
    assert refs[1].secondary_identifier == "ui_revamp"

    # 3. @agent:codex/perf_bench
    assert refs[2].target_kind == BigAtTargetKind.AGENT
    assert refs[2].primary_identifier == "codex"
    assert refs[2].secondary_identifier == "perf_bench"

    # 4. @bob/db_migration (shorthand)
    assert refs[3].target_kind == BigAtTargetKind.COLLABORATOR
    assert refs[3].primary_identifier == "bob"
    assert refs[3].secondary_identifier == "db_migration"

    # Verify stripped prompt
    cleaned = BigAtSyntaxParser.strip_references(prompt)
    assert "@" not in cleaned
    assert cleaned == "Please check and as well as and shorthand to fix the issue."


def test_zero_explanation_context_distillation() -> None:
    """Verifies technical essence extraction adhering to field boundaries."""
    findings = [f"Finding {i}: cache mismatch detected" for i in range(10)]
    rejections = ["Avoid modifying raw DB schema directly"]
    conclusions = [f"Decision {i}: adopted memory cache" for i in range(8)]
    anchors = [f"src/core/cache_v{i}.py" for i in range(12)]
    artifacts = ["art_cache_spec"]

    cfg = ContextBorrowingConfig(
        max_findings=3,
        max_conclusions=2,
        max_anchors=4,
    )

    distilled: DistilledSessionContext = ZeroExplanationContextExtractor.distill(
        source_session_id="sess_eng_001",
        title="Cache Optimization Review",
        core_goal="Reduce read latency by 50%",
        fact_findings=findings,
        rejected_attempts=rejections,
        accepted_conclusions=conclusions,
        code_anchors=anchors,
        key_artifact_ids=artifacts,
        config=cfg,
    )

    assert distilled.source_session_id == "sess_eng_001"
    assert distilled.title == "Cache Optimization Review"
    assert len(distilled.fact_findings) == 3
    assert len(distilled.rejected_attempts) == 1
    assert len(distilled.accepted_conclusions) == 2
    assert len(distilled.code_anchors) == 4
    assert distilled.key_artifact_ids == ["art_cache_spec"]
    assert distilled.estimated_tokens > 0


def test_context_borrowing_hydration() -> None:
    """Verifies rendering distilled contexts into structured XML prompt blocks."""
    ctx1 = DistilledSessionContext(
        source_session_id="sess_eng_1",
        title="Backend Auth Review",
        core_goal="Fix OAuth token race condition",
        fact_findings=["Token refresh fails under high concurrency"],
        rejected_attempts=["Do not add global mutex lock"],
        accepted_conclusions=["Use Redis distributed lock with TTL"],
        code_anchors=["app/services/auth.py:45"],
        key_artifact_ids=["art_lock_schema"],
    )

    bridge = ContextBorrowingBridge()
    block = bridge.hydrate_context_block([ctx1])

    assert "<borrowed_cross_session_context>" in block
    assert '<session source_id="sess_eng_1" title="Backend Auth Review">' in block
    assert "<core_goal>Fix OAuth token race condition</core_goal>" in block
    assert "<code_anchors>app/services/auth.py:45</code_anchors>" in block
    assert "Token refresh fails under high concurrency" in block
    assert "Do not add global mutex lock" in block
    assert "Use Redis distributed lock with TTL" in block
    assert "<artifacts>art_lock_schema</artifacts>" in block
    assert "</borrowed_cross_session_context>" in block

    # Empty context returns empty string
    assert bridge.hydrate_context_block([]) == ""


def test_context_borrowing_token_budget_guard() -> None:
    """Verifies strict token budget enforcement during context borrowing."""
    ctx_large = DistilledSessionContext(
        source_session_id="sess_large_1",
        title="Heavy System Diagnostics",
        core_goal="Resolve memory leak across 20 nodes",
        fact_findings=[f"Node {i} memory exceeds threshold" for i in range(20)],
        rejected_attempts=["Do not restart node blindly"],
        accepted_conclusions=["Patch garbage collector threshold"],
        code_anchors=["runtime/gc.py"],
    )

    strict_cfg = ContextBorrowingConfig(max_borrowed_tokens=60)
    bridge = ContextBorrowingBridge(strict_cfg)

    block = bridge.hydrate_context_block([ctx_large])

    token_count = get_token_count(block)
    assert token_count <= strict_cfg.max_borrowed_tokens
