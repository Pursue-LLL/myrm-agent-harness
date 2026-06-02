"""Tests for line ending detection, normalization, and preservation across edits.

Covers:
- detect_line_ending: CRLF, LF, empty, single-line, mixed
- normalize_line_endings: LF→LF, LF→CRLF, CRLF→LF, CRLF→CRLF, mixed, lone CR, idempotence
- StorageBackendStrategy.replace_text: CRLF preservation for exact + fuzzy match
- FileOperationService._execute_create: CRLF preservation when overwriting existing files
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.utils.line_endings import (
    detect_line_ending,
    normalize_line_endings,
)

# ── detect_line_ending ──────────────────────────────────────────────


class TestDetectLineEnding:
    def test_empty_string(self) -> None:
        assert detect_line_ending("") is None

    def test_no_newlines(self) -> None:
        assert detect_line_ending("single line no newline") is None

    def test_lf_only(self) -> None:
        assert detect_line_ending("line1\nline2\nline3\n") == "\n"

    def test_crlf_only(self) -> None:
        assert detect_line_ending("line1\r\nline2\r\nline3\r\n") == "\r\n"

    def test_crlf_takes_precedence_over_mixed(self) -> None:
        assert detect_line_ending("line1\r\nline2\nline3\n") == "\r\n"

    def test_large_content_scans_head_only(self) -> None:
        beyond_sample = "a" * 5000 + "\n" + "b" * 5000
        assert detect_line_ending(beyond_sample) is None

        within_sample = "a" * 3000 + "\n" + "b" * 5000
        assert detect_line_ending(within_sample) == "\n"

    def test_crlf_in_head(self) -> None:
        content = "first\r\nsecond\r\n" + "a" * 10000
        assert detect_line_ending(content) == "\r\n"

    def test_lone_cr_detected_as_none(self) -> None:
        """Lone CR (old Mac style) has no \\n so detect returns None."""
        assert detect_line_ending("line1\rline2\rline3\r") is None

    def test_crlf_at_sample_boundary_split(self) -> None:
        """CRLF split across the 4096 boundary: \\r at 4095, \\n at 4096.
        Only \\r is in head, no complete \\r\\n or \\n, so returns None."""
        content = "x" * 4095 + "\r\n" + "rest"
        assert detect_line_ending(content) is None

    def test_crlf_within_sample_boundary(self) -> None:
        """CRLF fully within sample window detects correctly."""
        content = "x" * 4094 + "\r\n" + "rest"
        assert detect_line_ending(content) == "\r\n"

    def test_crlf_just_beyond_sample(self) -> None:
        """CRLF entirely beyond the 4096 sample window."""
        content = "x" * 4097 + "\r\n"
        assert detect_line_ending(content) is None


# ── normalize_line_endings ──────────────────────────────────────────


class TestNormalizeLineEndings:
    def test_lf_to_lf(self) -> None:
        assert normalize_line_endings("a\nb\nc\n", "\n") == "a\nb\nc\n"

    def test_lf_to_crlf(self) -> None:
        assert normalize_line_endings("a\nb\nc\n", "\r\n") == "a\r\nb\r\nc\r\n"

    def test_crlf_to_lf(self) -> None:
        assert normalize_line_endings("a\r\nb\r\nc\r\n", "\n") == "a\nb\nc\n"

    def test_crlf_to_crlf(self) -> None:
        assert normalize_line_endings("a\r\nb\r\nc\r\n", "\r\n") == "a\r\nb\r\nc\r\n"

    def test_mixed_endings_to_lf(self) -> None:
        assert normalize_line_endings("a\r\nb\nc\r\n", "\n") == "a\nb\nc\n"

    def test_mixed_endings_to_crlf(self) -> None:
        assert normalize_line_endings("a\r\nb\nc\r\n", "\r\n") == "a\r\nb\r\nc\r\n"

    def test_lone_cr_to_lf(self) -> None:
        assert normalize_line_endings("a\rb\rc\r", "\n") == "a\nb\nc\n"

    def test_lone_cr_to_crlf(self) -> None:
        assert normalize_line_endings("a\rb\rc\r", "\r\n") == "a\r\nb\r\nc\r\n"

    def test_idempotent_crlf(self) -> None:
        text = "a\nb\n"
        once = normalize_line_endings(text, "\r\n")
        twice = normalize_line_endings(once, "\r\n")
        assert once == twice

    def test_idempotent_lf(self) -> None:
        text = "a\r\nb\r\n"
        once = normalize_line_endings(text, "\n")
        twice = normalize_line_endings(once, "\n")
        assert once == twice

    def test_no_newlines(self) -> None:
        assert normalize_line_endings("no newlines", "\n") == "no newlines"
        assert normalize_line_endings("no newlines", "\r\n") == "no newlines"


# ── StorageBackendStrategy.replace_text CRLF preservation ───────────


@pytest.mark.asyncio
async def test_replace_text_preserves_crlf() -> None:
    """Exact match on a CRLF file should produce a CRLF result."""
    from myrm_agent_harness.agent.meta_tools.file_ops.strategies.storage_strategy import (
        StorageBackendStrategy,
    )

    crlf_content = "line1\r\nline2\r\nline3\r\n"
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.get_text = AsyncMock(return_value=crlf_content)
    storage.put_text = AsyncMock()

    strategy = StorageBackendStrategy(storage)
    await strategy.replace_text("test.txt", "line2", "replaced")

    written = storage.put_text.call_args[0][1]
    assert "\r\n" in written
    assert "replaced\r\n" in written
    assert "\n" not in written.replace("\r\n", "")


@pytest.mark.asyncio
async def test_replace_text_lf_unchanged() -> None:
    """LF files should stay LF after replacement."""
    from myrm_agent_harness.agent.meta_tools.file_ops.strategies.storage_strategy import (
        StorageBackendStrategy,
    )

    lf_content = "line1\nline2\nline3\n"
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.get_text = AsyncMock(return_value=lf_content)
    storage.put_text = AsyncMock()

    strategy = StorageBackendStrategy(storage)
    await strategy.replace_text("test.txt", "line2", "replaced")

    written = storage.put_text.call_args[0][1]
    assert "\r\n" not in written
    assert "replaced\n" in written


@pytest.mark.asyncio
async def test_replace_text_fuzzy_preserves_crlf() -> None:
    """Fuzzy match path should also preserve CRLF."""
    from myrm_agent_harness.agent.meta_tools.file_ops.strategies.storage_strategy import (
        StorageBackendStrategy,
    )

    crlf_content = "  line1\r\n  line2\r\n  line3\r\n"
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.get_text = AsyncMock(return_value=crlf_content)
    storage.put_text = AsyncMock()

    fuzzy_result = MagicMock()
    fuzzy_result.success = True
    fuzzy_result.content = "  line1\n  replaced\n  line3\n"
    fuzzy_result.strategy = "whitespace_normalized"
    fuzzy_result.confidence = 0.95

    strategy = StorageBackendStrategy(storage)
    with patch(
        "myrm_agent_harness.utils.fuzzy_match.fuzzy_replace",
        return_value=fuzzy_result,
    ):
        await strategy.replace_text("test.txt", "line2_typo", "replaced")

    written = storage.put_text.call_args[0][1]
    assert "\r\n" in written
    assert "\n" not in written.replace("\r\n", "")


@pytest.mark.asyncio
async def test_replace_text_single_line_no_normalization() -> None:
    """Single-line file (no newlines) should skip normalization."""
    from myrm_agent_harness.agent.meta_tools.file_ops.strategies.storage_strategy import (
        StorageBackendStrategy,
    )

    content = "single line no newline"
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.get_text = AsyncMock(return_value=content)
    storage.put_text = AsyncMock()

    strategy = StorageBackendStrategy(storage)
    await strategy.replace_text("test.txt", "single", "replaced")

    written = storage.put_text.call_args[0][1]
    assert written == "replaced line no newline"
    assert "\r\n" not in written


# ── FileOperationService._execute_create CRLF preservation ─────────


@pytest.mark.asyncio
async def test_create_overwrite_preserves_crlf() -> None:
    """Overwriting an existing CRLF file should preserve CRLF endings."""
    from myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service import (
        FileOperationService,
    )
    from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
        OperationContext,
        OperationType,
    )

    context = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="test.bat",
        file_text="echo hello\necho world\n",
    )
    service = FileOperationService(context)

    mock_strategy = AsyncMock()
    mock_strategy.exists = AsyncMock(return_value=True)
    mock_strategy.read_file = AsyncMock(
        side_effect=[
            ["line1\r", "line2\r", ""],
            ["echo hello\r", "echo world\r", ""],
        ]
    )
    mock_strategy.write_file = AsyncMock()

    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory"
        ) as mock_factory,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain"
        ) as mock_validator,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_staleness_guard",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate"
        ),
    ):
        mock_factory.create_strategy.return_value = mock_strategy
        mock_validator.return_value.validate = AsyncMock()

        await service.execute()

    written = mock_strategy.write_file.call_args[0][1]
    assert "\r\n" in written
    assert "echo hello\r\n" in written


@pytest.mark.asyncio
async def test_create_new_file_no_normalization() -> None:
    """Creating a brand-new file should NOT alter line endings."""
    from myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service import (
        FileOperationService,
    )
    from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
        OperationContext,
        OperationType,
    )

    original_text = "new content\nline2\n"
    context = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="brand_new.txt",
        file_text=original_text,
    )
    service = FileOperationService(context)

    mock_strategy = AsyncMock()
    mock_strategy.exists = AsyncMock(return_value=False)
    mock_strategy.read_file = AsyncMock(return_value=["new content", "line2", ""])
    mock_strategy.write_file = AsyncMock()

    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory"
        ) as mock_factory,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain"
        ) as mock_validator,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_staleness_guard",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate"
        ),
    ):
        mock_factory.create_strategy.return_value = mock_strategy
        mock_validator.return_value.validate = AsyncMock()

        await service.execute()

    written = mock_strategy.write_file.call_args[0][1]
    assert written == original_text
    assert "\r\n" not in written
