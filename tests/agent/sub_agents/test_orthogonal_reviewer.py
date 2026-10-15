import pytest
from myrm_agent_harness.agent.sub_agents.orthogonal_reviewer import (
    ArbitrationStatus,
    BlindCleanContextReviewer,
    FindingCategory,
    FindingSeverity,
    IntentAlignmentReviewer,
    OrthogonalReviewArbiter,
    ReviewerPerspective,
)


@pytest.fixture
def intent_reviewer() -> IntentAlignmentReviewer:
    return IntentAlignmentReviewer()


@pytest.fixture
def blind_reviewer() -> BlindCleanContextReviewer:
    return BlindCleanContextReviewer()


@pytest.fixture
def arbiter() -> OrthogonalReviewArbiter:
    return OrthogonalReviewArbiter()


def test_intent_reviewer_drift_detection(intent_reviewer: IntentAlignmentReviewer) -> None:
    # Prompt explicitly requires SHA-256 checksum verification
    task_prompt = "重构工件传输层，必须实现完整性哈希校验防篡改"
    architecture_plan = "实现跨网关中继服务并在接收端校验 SHA-256"
    # Diff does not contain hash verification
    code_diff = """
    +class ArtifactRelay:
    +    def transfer(self, data: str) -> None:
    +        send_over_network(data)
    """
    files_touched = ["artifact_relay.py"]

    report = intent_reviewer.review(
        task_prompt=task_prompt,
        architecture_plan=architecture_plan,
        code_diff=code_diff,
        files_touched=files_touched,
    )

    assert report.perspective == ReviewerPerspective.INTENT_ALIGNMENT
    assert not report.passed
    assert any(f.category == FindingCategory.INTENT_DRIFT for f in report.findings)
    assert any(f.severity == FindingSeverity.CRITICAL for f in report.findings)


def test_intent_reviewer_over_engineering(intent_reviewer: IntentAlignmentReviewer) -> None:
    task_prompt = "一个简单的小修补，改下文案"
    architecture_plan = ""
    code_diff = "+# Simple patch"
    files_touched = [f"module_{i}.py" for i in range(12)]

    report = intent_reviewer.review(
        task_prompt=task_prompt,
        architecture_plan=architecture_plan,
        code_diff=code_diff,
        files_touched=files_touched,
    )

    assert any(f.category == FindingCategory.OVER_ENGINEERING for f in report.findings)
    assert any(f.severity == FindingSeverity.WARNING for f in report.findings)


def test_blind_clean_context_any_type_detection(blind_reviewer: BlindCleanContextReviewer) -> None:
    # Diff introduces prohibited Any type
    code_diff = """
    @@ -10,3 +10,4 @@
    +def parse_config(payload: Any) -> Any:
    +    return payload.get("data")
    """
    files_touched = ["config.py"]

    report = blind_reviewer.review(
        code_diff=code_diff,
        files_touched=files_touched,
    )

    assert report.perspective == ReviewerPerspective.BLIND_CLEAN_CONTEXT
    assert not report.passed
    assert any(f.category == FindingCategory.TYPE_SAFETY for f in report.findings)
    assert any("Any" in f.title for f in report.findings)


def test_blind_clean_context_zero_division_guard(blind_reviewer: BlindCleanContextReviewer) -> None:
    # Diff does division without guard
    code_diff = """
    @@ -25,2 +25,3 @@
    +avg_latency = total_ms / len(requests)
    """
    files_touched = ["telemetry.py"]

    report = blind_reviewer.review(
        code_diff=code_diff,
        files_touched=files_touched,
    )

    assert any(f.category == FindingCategory.BOUNDARY_EDGE_CASE for f in report.findings)
    assert any(f.severity == FindingSeverity.WARNING for f in report.findings)


def test_blind_clean_context_breaking_signature(blind_reviewer: BlindCleanContextReviewer) -> None:
    # Diff removes a public signature
    code_diff = """
    @@ -10,4 +10,2 @@
    -def fetch_user_profile(user_id: str) -> UserProfile:
    -    return db.query(user_id)
    """
    files_touched = ["user_service.py"]
    public_signatures = ["fetch_user_profile(user_id: str) -> UserProfile:"]

    report = blind_reviewer.review(
        code_diff=code_diff,
        files_touched=files_touched,
        public_signatures=public_signatures,
    )

    assert not report.passed
    assert any(f.category == FindingCategory.REGRESSION_RISK for f in report.findings)
    assert any(f.severity == FindingSeverity.CRITICAL for f in report.findings)


def test_arbiter_synthesis_and_deduplication(arbiter: OrthogonalReviewArbiter) -> None:
    session_id = "test-session-arbiter-1"
    # Scenario 1: Clean code without flaws
    clean_diff = """
    +def calculate_ratio(val: int, total: int) -> float:
    +    return val / max(1, total)
    """
    rep_a, rep_b, verdict = arbiter.conduct_full_review(
        session_id=session_id,
        task_prompt="计算比率函数",
        architecture_plan="",
        code_diff=clean_diff,
        files_touched=["math_utils.py"],
    )

    assert rep_a.passed
    assert rep_b.passed
    assert verdict.is_approved
    assert verdict.status == ArbitrationStatus.APPROVED
    assert len(verdict.auto_fix_prompts) == 0

    # Scenario 2: Code with critical flaws requiring auto-fix
    flawed_diff = """
    +def process_data(item: Any) -> None:
    +    pass
    """
    rep_a2, rep_b2, verdict2 = arbiter.conduct_full_review(
        session_id=session_id,
        task_prompt="处理数据",
        architecture_plan="",
        code_diff=flawed_diff,
        files_touched=["processor.py"],
    )

    assert not rep_b2.passed
    assert not verdict2.is_approved
    assert verdict2.status == ArbitrationStatus.BLOCKED_AUTO_FIX
    assert len(verdict2.auto_fix_prompts) > 0
    assert "Any" in verdict2.auto_fix_prompts[0]
