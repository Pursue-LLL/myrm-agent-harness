"""Archive security error contract and observability helpers.

[INPUT]
- logging::Logger (POS: Structured runtime logging sink.)
- observability.metrics::get_or_create_counter (POS: Harness metrics factory for low-cardinality counters.)

[OUTPUT]
- ArchiveSecurityCode: enum — canonical archive security error codes
- ArchiveSecurityViolation: dataclass — structured archive violation context
- ArchiveSecurityError: exception — typed archive security error wrapper
- classify_archive_security_issue: function — normalize typed/untyped errors to canonical violation
- format_archive_security_user_message: function — user-facing message without technical leakage
- log_archive_security_violation: function — emit structured violation logs
- is_executable_binary_content: function — executable signature detector (ELF/PE/Mach-O)

[POS]
Shared archive-security contract used by validation/extraction layers and
business-facing adapters to keep behavior consistent across entry points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.observability.metrics import get_or_create_counter

_MACHO_MAGIC_PREFIXES = (
    b"\xfe\xed\xfa\xce",  # Mach-O 32 (big-endian)
    b"\xce\xfa\xed\xfe",  # Mach-O 32 (little-endian)
    b"\xfe\xed\xfa\xcf",  # Mach-O 64 (big-endian)
    b"\xcf\xfa\xed\xfe",  # Mach-O 64 (little-endian)
    b"\xca\xfe\xba\xbe",  # Fat binary (big-endian)
    b"\xbe\xba\xfe\xca",  # Fat binary (little-endian)
)


class ArchiveSecurityCode(StrEnum):
    """Canonical archive security error codes."""

    ENTRY_LIMIT_EXCEEDED = "archive_security.entry_limit_exceeded"
    TOTAL_SIZE_EXCEEDED = "archive_security.total_size_exceeded"
    COMPRESSION_RATIO_EXCEEDED = "archive_security.compression_ratio_exceeded"
    EXECUTABLE_BINARY_DETECTED = "archive_security.executable_binary_detected"


@dataclass(frozen=True, slots=True)
class ArchiveSecurityViolation:
    """Structured archive security violation context."""

    code: ArchiveSecurityCode
    source: str
    actual: int | float | str | None = None
    limit: int | float | str | None = None


class ArchiveSecurityError(ValueError):
    """Typed archive security error with canonical violation metadata."""

    def __init__(self, violation: ArchiveSecurityViolation, developer_message: str):
        super().__init__(developer_message)
        self.violation = violation


_archive_security_violation_total = get_or_create_counter(
    "myrm_archive_security_violation_total",
    "Total archive security violations grouped by code/source.",
    ("code", "source"),
)


def classify_archive_security_issue(error_or_text: BaseException | str) -> ArchiveSecurityViolation | None:
    """Normalize typed/untyped archive errors to a canonical violation."""
    if isinstance(error_or_text, ArchiveSecurityError):
        return error_or_text.violation

    text = error_or_text if isinstance(error_or_text, str) else str(error_or_text)
    normalized = text.lower()

    if (
        "too many entries" in normalized
        or "zip 条目过多" in normalized
        or "zip 文件条目数过多" in normalized
    ):
        return ArchiveSecurityViolation(
            code=ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED,
            source="legacy_untyped_error",
        )
    if "zip bomb detected" in normalized or "压缩比异常" in text:
        return ArchiveSecurityViolation(
            code=ArchiveSecurityCode.COMPRESSION_RATIO_EXCEEDED,
            source="legacy_untyped_error",
        )
    if "total uncompressed size" in normalized or "解压后体积超出限制" in text:
        return ArchiveSecurityViolation(
            code=ArchiveSecurityCode.TOTAL_SIZE_EXCEEDED,
            source="legacy_untyped_error",
        )
    if "executable binary member" in normalized or "可执行二进制文件" in text:
        return ArchiveSecurityViolation(
            code=ArchiveSecurityCode.EXECUTABLE_BINARY_DETECTED,
            source="legacy_untyped_error",
        )
    return None


def format_archive_security_user_message(violation: ArchiveSecurityViolation) -> str:
    """Return user-facing archive block reason without exposing internals."""
    if violation.code == ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED:
        return "上传被系统安全拦截：ZIP 文件条目数过多。"
    if violation.code == ArchiveSecurityCode.TOTAL_SIZE_EXCEEDED:
        return "上传被系统安全拦截：ZIP 解压后体积超出限制。"
    if violation.code == ArchiveSecurityCode.COMPRESSION_RATIO_EXCEEDED:
        return "上传被系统安全拦截：ZIP 压缩比异常。"
    if violation.code == ArchiveSecurityCode.EXECUTABLE_BINARY_DETECTED:
        return "上传被系统安全拦截：ZIP 包含可执行二进制文件。"
    return "上传被系统安全拦截：压缩包不符合安全策略。"


def log_archive_security_violation(
    logger: logging.Logger,
    violation: ArchiveSecurityViolation,
) -> None:
    """Emit a structured archive security violation log."""
    _archive_security_violation_total.labels(
        code=violation.code.value,
        source=violation.source,
    ).inc()
    logger.warning(
        "archive_security_violation code=%s source=%s actual=%s limit=%s",
        violation.code.value,
        violation.source,
        _format_metric_value(violation.actual),
        _format_metric_value(violation.limit),
    )


def is_executable_binary_content(content: bytes) -> bool:
    """Return True when content matches known executable binary signatures."""
    if content.startswith(b"\x7fELF"):
        return True
    if any(content.startswith(prefix) for prefix in _MACHO_MAGIC_PREFIXES):
        return True
    return _looks_like_pe_binary(content)


def _looks_like_pe_binary(content: bytes) -> bool:
    if len(content) < 0x40 or not content.startswith(b"MZ"):
        return False
    pe_header_offset = int.from_bytes(content[0x3C:0x40], "little", signed=False)
    if pe_header_offset < 0x40 or pe_header_offset + 4 > len(content):
        return False
    return content[pe_header_offset : pe_header_offset + 4] == b"PE\x00\x00"


def _format_metric_value(value: int | float | str | None) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    return f"{value:.4f}"

