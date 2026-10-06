"""Unit tests for progressive content density ladder and peek/skim token throttler."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.content_density_ladder import (
    ContentDensityLadderThrottler,
)
from myrm_agent_harness.runtime.context.content_density_ladder_types import (
    DensityLevel,
    DensityReadingRequest,
)

SAMPLE_PYTHON_CODE = '''"""Sample module docstring."""

class AuthenticationService:
    """Manages user authentication and tokens."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def authenticate_user(self, username: str, token: str) -> bool:
        """Validate bearer credentials against database."""
        return len(token) > 10

    async def refresh_session_async(self, session_id: str) -> str:
        """Issue fresh token for active session."""
        return f"token_for_{session_id}"


def health_check() -> str:
    """Return health ping status."""
    return "ok"
'''

SAMPLE_MARKDOWN = """# System Architecture Overview
This document describes the architectural layout of the platform.

## 1. Gateway Component
The gateway terminates TLS and routes traffic.

### 1.1 Rate Limiting
Enforces per-tenant quotas.

## 2. Storage Tier
PostgreSQL and S3 for persistence.
"""


@pytest.fixture
def throttler() -> ContentDensityLadderThrottler:
    return ContentDensityLadderThrottler()


def test_level_1_peek_python_ast_extraction(throttler: ContentDensityLadderThrottler) -> None:
    """Validate Level 1 (PEEK) outline extraction of Python classes and functions."""
    req = DensityReadingRequest(file_path="src/auth.py", level=DensityLevel.PEEK)
    res = throttler.read_with_density(SAMPLE_PYTHON_CODE, req)

    assert not res.is_refused
    assert res.level == DensityLevel.PEEK
    assert "class AuthenticationService" in res.rendered_content
    assert "def authenticate_user()" in res.rendered_content
    assert "async def refresh_session_async()" in res.rendered_content
    assert "def health_check()" in res.rendered_content
    # Level 1 PEEK does NOT include docstring summaries
    assert "↳ Summary:" not in res.rendered_content
    assert res.savings_ratio > 0.4
    assert len(res.outline_nodes) == 5


def test_level_1_peek_markdown_heading_extraction(throttler: ContentDensityLadderThrottler) -> None:
    """Validate Level 1 (PEEK) outline extraction of Markdown headings."""
    req = DensityReadingRequest(file_path="docs/arch.md", level=DensityLevel.PEEK)
    res = throttler.read_with_density(SAMPLE_MARKDOWN, req)

    assert not res.is_refused
    assert "# System Architecture Overview" in res.rendered_content
    assert "## 1. Gateway Component" in res.rendered_content
    assert "### 1.1 Rate Limiting" in res.rendered_content
    assert "## 2. Storage Tier" in res.rendered_content


def test_level_2_skim_outline_with_summaries(throttler: ContentDensityLadderThrottler) -> None:
    """Validate Level 2 (SKIM) concentrated view with docstring summaries."""
    req = DensityReadingRequest(file_path="src/auth.py", level=DensityLevel.SKIM)
    res = throttler.read_with_density(SAMPLE_PYTHON_CODE, req)

    assert not res.is_refused
    assert res.level == DensityLevel.SKIM
    assert "↳ Summary: Manages user authentication and tokens." in res.rendered_content
    assert "↳ Summary: Validate bearer credentials against database." in res.rendered_content
    assert "↳ Summary: Issue fresh token for active session." in res.rendered_content
    assert "↳ Summary: Return health ping status." in res.rendered_content


def test_level_3_range_precise_slice(throttler: ContentDensityLadderThrottler) -> None:
    """Validate Level 3 (RANGE) targeted line slicing with 1-based indexing."""
    req = DensityReadingRequest(
        file_path="src/auth.py",
        level=DensityLevel.RANGE,
        range_start=9,
        range_end=12,
    )
    res = throttler.read_with_density(SAMPLE_PYTHON_CODE, req)

    assert not res.is_refused
    assert res.level == DensityLevel.RANGE
    assert "Lines 9-12 of 20" in res.rendered_content
    assert "def authenticate_user" in res.rendered_content
    assert res.savings_ratio > 0.5


def test_level_4_full_within_safe_limit(throttler: ContentDensityLadderThrottler) -> None:
    """Validate Level 4 (FULL) pass-through when file size is within safety threshold."""
    req = DensityReadingRequest(
        file_path="src/auth.py",
        level=DensityLevel.FULL,
        max_full_size_bytes=10_000,
    )
    res = throttler.read_with_density(SAMPLE_PYTHON_CODE, req)

    assert not res.is_refused
    assert res.rendered_content == SAMPLE_PYTHON_CODE
    assert res.savings_ratio == 0.0


def test_level_4_full_lazy_object_safeguard_refusal(throttler: ContentDensityLadderThrottler) -> None:
    """Validate Lazy Object Safeguard rejecting oversized file full reading."""
    huge_data = "col1,col2,col3,col4,col5\n" + ("1,foo,bar,baz,data_entry\n" * 5000)
    req = DensityReadingRequest(
        file_path="data/huge_dump.csv",
        level=DensityLevel.FULL,
        max_full_size_bytes=5_000,  # File is ~125KB, limit is 5KB
    )
    res = throttler.read_with_density(huge_data, req)

    assert res.is_refused
    assert res.rendered_content == ""
    assert res.refusal_reason is not None
    assert "Full cat refused: file size" in res.refusal_reason
    assert "exceeds safe limit" in res.refusal_reason
    assert res.savings_ratio == 1.0


def test_syntax_error_fallback_regex(throttler: ContentDensityLadderThrottler) -> None:
    """Validate graceful regex fallback for incomplete or syntactically invalid Python."""
    broken_code = "class BrokenClass:\n    def broken_method(\n"
    req = DensityReadingRequest(file_path="broken.py", level=DensityLevel.PEEK)
    res = throttler.read_with_density(broken_code, req)

    assert not res.is_refused
    assert "class BrokenClass" in res.rendered_content
    assert "def broken_method" in res.rendered_content
