"""Tests for archive_security.py contract helpers."""

import logging

from myrm_agent_harness.backends.skills.scanning import archive_security
from myrm_agent_harness.backends.skills.scanning.archive_security import (
    ArchiveSecurityCode,
    ArchiveSecurityError,
    ArchiveSecurityViolation,
    classify_archive_security_issue,
    format_archive_security_user_message,
    is_executable_binary_content,
)


def test_classify_returns_violation_for_typed_error():
    violation = ArchiveSecurityViolation(
        code=ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED,
        source="unit_test",
        actual=10,
        limit=9,
    )
    error = ArchiveSecurityError(violation, "ZIP contains too many entries (10 > 9)")

    parsed = classify_archive_security_issue(error)

    assert parsed == violation


def test_classify_legacy_entry_limit_message():
    parsed = classify_archive_security_issue("ZIP 条目过多 (5000 > 4096)")

    assert parsed is not None
    assert parsed.code == ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED


def test_format_user_message_for_entry_limit():
    violation = ArchiveSecurityViolation(
        code=ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED,
        source="unit_test",
    )

    assert format_archive_security_user_message(violation) == "上传被系统安全拦截：ZIP 文件条目数过多。"


def test_classify_legacy_compression_ratio_message():
    parsed = classify_archive_security_issue("上传被系统安全拦截：ZIP 压缩比异常。")

    assert parsed is not None
    assert parsed.code == ArchiveSecurityCode.COMPRESSION_RATIO_EXCEEDED


def test_classify_legacy_total_size_message():
    parsed = classify_archive_security_issue("上传被系统安全拦截：ZIP 解压后体积超出限制。")

    assert parsed is not None
    assert parsed.code == ArchiveSecurityCode.TOTAL_SIZE_EXCEEDED


def test_classify_legacy_executable_message():
    parsed = classify_archive_security_issue("ZIP contains executable binary member: payload.bin")

    assert parsed is not None
    assert parsed.code == ArchiveSecurityCode.EXECUTABLE_BINARY_DETECTED


def test_format_user_message_for_executable_binary():
    violation = ArchiveSecurityViolation(
        code=ArchiveSecurityCode.EXECUTABLE_BINARY_DETECTED,
        source="unit_test",
    )

    assert format_archive_security_user_message(violation) == "上传被系统安全拦截：ZIP 包含可执行二进制文件。"


def test_is_executable_binary_content_detects_elf():
    assert is_executable_binary_content(b"\x7fELF\x02\x01\x01\x00")


def test_is_executable_binary_content_rejects_plain_text():
    assert not is_executable_binary_content(b"MZ this is just markdown text")


def test_is_executable_binary_content_detects_pe_signature():
    payload = bytearray(128)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x40).to_bytes(4, "little")
    payload[0x40:0x44] = b"PE\x00\x00"
    assert is_executable_binary_content(bytes(payload))


class _FakeLabeledCounter:
    def __init__(self) -> None:
        self.inc_calls = 0

    def inc(self, amount: float = 1) -> None:
        self.inc_calls += 1


class _FakeCounter:
    def __init__(self) -> None:
        self.labels_kwargs: dict[str, str] | None = None
        self.labeled_counter = _FakeLabeledCounter()

    def labels(self, **kwargs: str) -> _FakeLabeledCounter:
        self.labels_kwargs = kwargs
        return self.labeled_counter


def test_log_archive_security_violation_increments_metric(monkeypatch) -> None:
    fake_counter = _FakeCounter()
    monkeypatch.setattr(archive_security, "_archive_security_violation_total", fake_counter)
    violation = ArchiveSecurityViolation(
        code=ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED,
        source="safe_extract_zip",
        actual=5000,
        limit=4096,
    )

    archive_security.log_archive_security_violation(logging.getLogger(__name__), violation)

    assert fake_counter.labels_kwargs == {
        "code": ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED.value,
        "source": "safe_extract_zip",
    }
    assert fake_counter.labeled_counter.inc_calls == 1
