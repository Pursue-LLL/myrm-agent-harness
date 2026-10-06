# [POS] tests/toolkits/memory/test_dual_track_extraction.py
# [INPUT] pytest, myrm_agent_harness.toolkits.memory.dual_track_extraction
# [OUTPUT] TestDualTrackExtractionSuite

from myrm_agent_harness.toolkits.memory.dual_track_extraction import (
    DualTrackExtractionGateway,
    DualTrackSemanticClassifier,
    ExtractionDestiny,
    ExtractionDestinyReport,
    ExtractionTrackKind,
)


def test_classifier_procedural_detection() -> None:
    """Verify classifier correctly recognizes operational procedures, SOPs, and troubleshooting guidelines."""
    classifier = DualTrackSemanticClassifier()

    proc_texts = [
        "遇到线上504报警先检查负载均衡器健康检查状态",
        "以后写Go代码记得加上context超时控制",
        "when service crashes always check systemd logs first",
        "如果客户问退款一律引导至财务审批工单页面",
    ]

    for text in proc_texts:
        track, confidence, reason = classifier.classify(text)
        assert track in (ExtractionTrackKind.PROCEDURAL_RULE, ExtractionTrackKind.DUAL_TRACK)
        assert confidence >= 0.8
        assert reason != ""


def test_classifier_fact_detection() -> None:
    """Verify classifier correctly recognizes declarative user facts and preferences."""
    classifier = DualTrackSemanticClassifier()

    fact_texts = [
        "我是一名全栈架构师，在做一人公司",
        "核心技术栈是Python与Rust",
        "我们的唯一数据库是PostgreSQL",
        "my name is Alice and i prefer dark theme",
    ]

    for text in fact_texts:
        track, confidence, reason = classifier.classify(text)
        assert track in (ExtractionTrackKind.FACT_PROFILE, ExtractionTrackKind.DUAL_TRACK)
        assert confidence >= 0.8
        assert reason != ""


def test_classifier_dual_track_and_no_signal() -> None:
    """Verify composite statements classify as DUAL_TRACK and chitchat as NO_SIGNAL."""
    classifier = DualTrackSemanticClassifier()

    dual_text = "我叫李四在做独立开发者，以后写代码遇到错误务必先查本地日志"
    track_dual, conf_dual, _ = classifier.classify(dual_text)
    assert track_dual == ExtractionTrackKind.DUAL_TRACK
    assert conf_dual >= 0.85

    chitchat_texts = [
        "好的收到",
        "哈哈今天天气真不错",
        "ok",
        "thanks a lot",
    ]
    for text in chitchat_texts:
        track, _conf, reason = classifier.classify(text)
        assert track == ExtractionTrackKind.NO_SIGNAL
        assert "No actionable" in reason or "too short" in reason


def test_gateway_procedural_routing_and_anti_silent_drop() -> None:
    """Verify gateway extracts actionable rules without silently dropping operational instructions."""
    gateway = DualTrackExtractionGateway()

    instruction = "遇到线上报警先检查网关状态，并记录排障日志"
    report: ExtractionDestinyReport = gateway.process_utterance(instruction, domain="devops")

    assert report.destiny == ExtractionDestiny.STORED_PROCEDURAL
    assert report.track == ExtractionTrackKind.PROCEDURAL_RULE
    assert len(report.extracted_rules) == 1
    assert len(report.extracted_facts) == 0

    rule = report.extracted_rules[0]
    assert rule.domain == "devops"
    assert "先检查" in rule.action_guideline or "网关状态" in rule.action_guideline
    assert rule.rule_id.startswith("proc-rule-")


def test_gateway_no_signal_transparent_discard_reason() -> None:
    """Verify gateway provides transparent discard reason instead of silently vanishing."""
    gateway = DualTrackExtractionGateway()

    chitchat = "今天中午吃拉面吧"
    report: ExtractionDestinyReport = gateway.process_utterance(chitchat)

    assert report.destiny == ExtractionDestiny.DISCARDED_NO_SIGNAL
    assert report.track == ExtractionTrackKind.NO_SIGNAL
    assert len(report.extracted_facts) == 0
    assert len(report.extracted_rules) == 0
    assert report.discard_reason != ""
    assert "No actionable" in report.discard_reason
