"""Unit tests for Listen-Translate-Remember-Act (LTRA) cognitive pipeline.

[POS]
随身感知“听—译—记—办”全链路单测套件。端到端验证说话人身份解析、
敏感机密拦截、高纯度事实四元组蒸馏、毫秒级原声防篡改锚定与沙箱任务草稿生成。

[INPUT]
- 模拟多说话人外出访谈与现场会议时间戳切片

[OUTPUT]
- 严格断言四元组完整性、时间戳溯源防篡改摘要与沙箱任务派发草稿
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.ltra import (
    AudioFactDistillationWorker,
    AudioTimestampAnchor,
    CognitiveFactQuadruple,
    DiarizedTranscriptSegment,
    FollowupTaskDraftBuilder,
    SensitiveAudioFactGuard,
    SpeakerIdentityResolver,
)


def test_speaker_identity_resolver_explicit_and_heuristics() -> None:
    """Test manual alias registration and conversational self-introduction mining."""
    resolver = SpeakerIdentityResolver(initial_aliases={"spk_0": "张总(客户决策人)"})
    assert resolver.resolve("spk_0") == "张总(客户决策人)"

    # Heuristic inference from self-introduction
    intro_text = "大家好，我是李工，负责本次供应链系统交付。"
    inferred = resolver.resolve("spk_1", segment_text=intro_text)
    assert inferred == "李工"
    assert resolver.resolve("spk_1") == "李工"

    # Fallback for unknown
    assert resolver.resolve("unknown") == "参会人员"


def test_sensitive_audio_fact_guard_confidentiality_detection() -> None:
    """Test detection and redaction of commercial pricing and confidential disclosures."""
    commercial_leak = "张总，我们内部最低报价是500万元，千万别外传。"
    is_confidential, reasons = SensitiveAudioFactGuard.evaluate_confidentiality(commercial_leak)
    assert is_confidential is True
    assert "Commercial Pricing or Secret Disclosure" in reasons

    sanitized = SensitiveAudioFactGuard.sanitize_for_public_log(commercial_leak)
    assert "[COMMERCIAL_CONFIDENTIAL_REDACTED]" in sanitized

    benign_text = "我们下周二准时启动对接测试。"
    is_benign, benign_reasons = SensitiveAudioFactGuard.evaluate_confidentiality(benign_text)
    assert is_benign is False
    assert len(benign_reasons) == 0


def test_audio_fact_distillation_worker_extracts_quadruples() -> None:
    """Test distillation of multi-turn conversation into structured facts with anchors."""
    resolver = SpeakerIdentityResolver({"spk_client": "张总", "spk_our": "我方架构师"})
    worker = AudioFactDistillationWorker(identity_resolver=resolver)

    turns = [
        # Chatter / noise (should be filtered)
        DiarizedTranscriptSegment(
            speaker_id="spk_client",
            text="嗯，好，天气不错。",
            start_ms=0,
            end_ms=1500,
            confidence=0.9,
        ),
        # Real demand & blocker
        DiarizedTranscriptSegment(
            speaker_id="spk_client",
            text="我们核心诉求是支持离线私有化部署，担心内网升级复杂度太高，这是主要风险。",
            start_ms=2000,
            end_ms=8500,
            confidence=0.95,
        ),
        # Verbal commitment
        DiarizedTranscriptSegment(
            speaker_id="spk_our",
            text="张总放心，我们承诺在两周内交付离线沙箱安装包与升级脚本，完全支持这个要求。",
            start_ms=9000,
            end_ms=15000,
            confidence=0.92,
        ),
    ]

    facts = worker.distill_facts(turns, audio_id="audio_meeting_101", project_id="proj_enterprise")
    assert len(facts) >= 1

    # First distilled fact from client demand
    fact_1 = facts[0]
    assert fact_1.subject == "张总"
    assert "支持离线私有化部署" in fact_1.demand
    assert "内网升级复杂度太高" in fact_1.pending_issue
    assert len(fact_1.anchors) == 1

    anchor = fact_1.anchors[0]
    assert anchor.audio_id == "audio_meeting_101"
    assert anchor.start_ms == 2000
    assert anchor.end_ms == 8500
    assert len(anchor.sha256_digest) == 16


def test_followup_task_draft_builder_and_idempotency() -> None:
    """Test converting confirmed fact into sandbox task specification with idempotency."""
    anchor = AudioTimestampAnchor.create(
        audio_id="rec_001",
        start_ms=1000,
        end_ms=5000,
        verbatim_quote="希望支持钉钉与企业微信双通道同步",
    )
    fact = CognitiveFactQuadruple.create(
        subject="李总",
        demand="支持钉钉与企业微信双通道消息同步",
        commitment="三天内提供原型方案",
        pending_issue="第三方凭据权限尚未审批",
        anchors=[anchor],
        project_id="proj_im",
    )

    draft_1 = FollowupTaskDraftBuilder.build_draft(fact, target_agent_role="系统集成专家")
    assert draft_1.source_fact_id == fact.fact_id
    assert "【随身外设感知派办】" in draft_1.title
    assert "workspace/followups/" in draft_1.sandbox_deliverable_path
    assert len(draft_1.action_plan_steps) == 4
    assert len(draft_1.idempotency_token) == 20

    # Same fact and role should yield identical idempotency token
    draft_2 = FollowupTaskDraftBuilder.build_draft(fact, target_agent_role="系统集成专家")
    assert draft_1.idempotency_token == draft_2.idempotency_token
