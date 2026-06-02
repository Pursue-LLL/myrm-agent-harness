"""myrm_agent_harness.utils package lazy exports (__getattr__ / __dir__)."""

import pytest

import myrm_agent_harness.utils as utils_pkg


def test_lazy_resolve_public_exports() -> None:
    for name in (
        "CancellationToken",
        "SteeringToken",
        "RWLock",
        "parse_front_matter",
        "extract_original_content",
        "format_documents_with_metadata",
        "format_crawl_results",
        "wrap_with_external_sources_tag",
        "wrap_with_tool_output_tag",
        "TruncationStats",
    ):
        obj = getattr(utils_pkg, name)
        assert obj is not None


def test_getattr_unknown_raises() -> None:
    with pytest.raises(AttributeError, match="has no attribute"):
        _ = utils_pkg.definitely_not_a_utils_export_zzzz


def test_dir_contains_exports() -> None:
    names = utils_pkg.__dir__()
    assert "format_documents_with_metadata" in names
    assert "TruncationStats" in names
