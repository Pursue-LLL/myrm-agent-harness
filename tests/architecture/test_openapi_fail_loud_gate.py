"""Architecture gate: OpenAPI enabled services must fail loud when zero tools load.

Policy: no silent zero-tool agents when OpenAPI services are enabled.
See TOOL_DESIGN_STRATEGY.md §OpenAPI 拒绝 and agent/_factory/_ARCH.md.
"""

from __future__ import annotations

from pathlib import Path

_HARNESS_SRC = Path(__file__).resolve().parents[2] / "src" / "myrm_agent_harness"


def test_builder_openapi_load_failure_is_fail_loud() -> None:
    """builder.py must raise openapi_load_failed when enabled services produce zero tools."""
    builder_path = _HARNESS_SRC / "agent" / "_factory" / "builder.py"
    source = builder_path.read_text(encoding="utf-8")
    assert 'error_code="openapi_load_failed"' in source, (
        "OpenAPI load failures must raise ConfigIncompleteError(openapi_load_failed)"
    )
    assert "enabled_openapi_count > 0 and not openapi_all" in source, "OpenAPI fail-loud guard condition missing"


def test_builder_openapi_budget_failure_remains_fail_loud() -> None:
    """Regression: Turn1 budget guard must remain fail-loud alongside load guard."""
    builder_path = _HARNESS_SRC / "agent" / "_factory" / "builder.py"
    source = builder_path.read_text(encoding="utf-8")
    assert 'error_code="openapi_direct_budget_exceeded"' in source
