"""
Unit tests for Sanitized One-Click Debug Share and Encrypted Diagnostic Dump.
Tests ZeroLeak redaction, vitals collection, and ephemeral self-destructing share links.
"""

from myrm_agent_harness.observability.sanitized_debug_dump import (
    RedactionRuleType,
    SanitizedDebugPackager,
    ZeroLeakRedactor,
)


def test_zero_leak_redactor_rules() -> None:
    redactor = ZeroLeakRedactor()

    raw_sample = (
        "Error in /Users/johndoe/my_repo/main.py at line 42.\n"
        "Failed connecting to API with key sk-proj-1234567890abcdef12345678 and token ghp_1234567890abcdef1234567890abcdef1234.\n"
        "Authorization: Bearer mySecretBearerToken1234567890\n"
        "Contact developer at john.smith@company.org or check host 192.168.5.12"
    )

    clean_text, audits = redactor.sanitize(raw_sample)

    # 1. 验证全部敏感信息均被物理抹除
    assert "sk-proj-" not in clean_text
    assert "ghp_" not in clean_text
    assert "mySecretBearerToken" not in clean_text
    assert "/Users/johndoe" not in clean_text
    assert "john.smith@company.org" not in clean_text
    assert "192.168.5.12" not in clean_text

    # 2. 验证替换伪标签存在
    assert "[REDACTED_API_KEY]" in clean_text
    assert "Bearer [REDACTED_TOKEN]" in clean_text
    assert "[USER_WORKSPACE]/path" in clean_text
    assert "[REDACTED_EMAIL]" in clean_text
    assert "[REDACTED_IP]" in clean_text

    # 3. 验证审计记录
    rules_detected = {a.rule_type for a in audits}
    assert RedactionRuleType.API_KEY in rules_detected
    assert RedactionRuleType.BEARER_TOKEN in rules_detected
    assert RedactionRuleType.FILE_SYSTEM_PATH in rules_detected
    assert RedactionRuleType.EMAIL_ADDRESS in rules_detected
    assert RedactionRuleType.IP_ADDRESS in rules_detected


def test_sanitized_debug_packager_dump_creation() -> None:
    packager = SanitizedDebugPackager()

    raw_logs = [
        "2026-10-12T10:00:00Z [INFO] Initializing service at /home/ubuntu/app/server.py",
        "2026-10-12T10:00:01Z [ERROR] OpenAI request failed with key sk-1234567890abcdef1234567890",
    ]
    raw_traces = [
        {"agent": "coder", "file": "/home/ubuntu/code/test.py", "token": "Bearer abcdef1234567890abcdef12"},
    ]

    dump = packager.create_sanitized_dump(
        raw_logs=raw_logs,
        recent_traces=raw_traces,
        user_note="My private key sk-999999999999999999999999 is not working",
    )

    assert dump.dump_id.startswith("dump_")
    assert len(dump.checksum_sha256) == 64
    assert dump.total_redacted_count >= 3

    # 验证日志与 Trace 均已被安全清洗
    for log in dump.sanitized_logs:
        assert "/home/ubuntu" not in log
        assert "sk-" not in log

    assert "[USER_WORKSPACE]/path" in dump.recent_traces[0]["file"]
    assert "Bearer [REDACTED_TOKEN]" in dump.recent_traces[0]["token"]
    assert "[REDACTED_API_KEY]" in dump.user_note


def test_ephemeral_share_link_lifecycle_and_self_destruction() -> None:
    packager = SanitizedDebugPackager(share_ttl_hours=48, max_views_before_burn=3)

    dump = packager.create_sanitized_dump(
        raw_logs=["Log entry 1", "Log entry 2"],
        user_note="Diagnostic dump for community support",
    )

    link = packager.create_ephemeral_link(dump.dump_id)
    assert link.share_token.startswith("share_")
    assert link.remaining_views == 3
    assert not link.is_destroyed

    # 第一次访问
    d1, err1 = packager.consume_ephemeral_link(link.share_token)
    assert err1 is None
    assert d1 is not None
    assert link.remaining_views == 2

    # 第二次访问
    d2, err2 = packager.consume_ephemeral_link(link.share_token)
    assert err2 is None
    assert d2 is not None
    assert link.remaining_views == 1

    # 第三次访问 (达到最大限制并触发销毁)
    d3, err3 = packager.consume_ephemeral_link(link.share_token)
    assert err3 is None
    assert d3 is not None
    assert link.remaining_views == 0
    assert link.is_destroyed is True

    # 第四次访问 (已被阅后即焚粉碎)
    d4, err4 = packager.consume_ephemeral_link(link.share_token)
    assert d4 is None
    assert err4 is not None
    assert "已自毁" in err4 or "销毁" in err4
