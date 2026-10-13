"""Tests for omni_reference slice extractor in myrm_agent_harness.

[INPUT]
- myrm_agent_harness.agent.context_management.omni_reference::OmniReferenceExtractor
- myrm_agent_harness.agent.context_management.omni_reference::format_omni_context_slices
- myrm_agent_harness.agent.context_management.omni_reference::ReferenceTarget

[OUTPUT]
- Unit tests verifying 5-dimensional reference parsing, bounded slice extraction, and prompt block formatting

[POS]
Unit test suite under tests/agent/context_management/.
"""

from myrm_agent_harness.agent.context_management.omni_reference import (
    OmniReferenceExtractor,
    ReferenceTarget,
    format_omni_context_slices,
)


def test_parse_references_from_text_five_dimensions() -> None:
    """Verify OmniReferenceExtractor correctly parses all 5 reference dimensions without duplicates."""
    text = (
        "Please check @file:src/main.py and relate it to @session:sess_102. "
        "Also inspect @artifact:art_build_report, assign to @agent:code_reviewer, "
        "and link to @task:task_404. Repeated @file:src/main.py should be deduped."
    )

    targets = OmniReferenceExtractor.parse_references_from_text(text)
    assert len(targets) == 5

    dims = [t.dimension for t in targets]
    assert dims == ["file", "session", "artifact", "agent", "task"]

    target_ids = [t.target_id for t in targets]
    assert target_ids == ["src/main.py", "sess_102", "art_build_report", "code_reviewer", "task_404"]


def test_create_slice_with_truncation_protection() -> None:
    """Verify that slices exceeding character limit are safely truncated."""
    target = ReferenceTarget(dimension="session", target_id="sess_123", label="Prior Session")
    long_content = "X" * 3500

    slice_res = OmniReferenceExtractor.create_slice(target, long_content)

    assert slice_res.dimension == "session"
    assert slice_res.target_id == "sess_123"
    assert slice_res.is_truncated is True
    assert "[truncated for context efficiency]" in slice_res.content_slice
    assert len(slice_res.content_slice) < 2100
    assert slice_res.provenance_uri == "myrm://session/sess_123"


def test_create_slice_short_content_not_truncated() -> None:
    """Verify that short slice content is not truncated and calculates token estimate."""
    target = ReferenceTarget(dimension="artifact", target_id="art_1", label="Chart SVG")
    content = "<svg>...</svg>"

    slice_res = OmniReferenceExtractor.create_slice(target, content)

    assert slice_res.is_truncated is False
    assert slice_res.content_slice == "<svg>...</svg>"
    assert slice_res.token_estimate >= 1


def test_format_omni_context_slices_block() -> None:
    """Verify that formatting context slices produces clean immutable XML blocks."""
    t1 = ReferenceTarget(dimension="file", target_id="test.py", label="test.py")
    t2 = ReferenceTarget(dimension="task", target_id="task_9", label="Bug fix")

    s1 = OmniReferenceExtractor.create_slice(t1, "def hello(): pass")
    s2 = OmniReferenceExtractor.create_slice(t2, "Status: In Progress\nPriority: P0")

    formatted = format_omni_context_slices([s1, s2])

    assert "<!-- OMNI_CONTEXT_REFERENCE_BLOCK: START -->" in formatted
    assert '<slice dimension="file" target_id="test.py"' in formatted
    assert '<slice dimension="task" target_id="task_9"' in formatted
    assert "def hello(): pass" in formatted
    assert "<!-- OMNI_CONTEXT_REFERENCE_BLOCK: END -->" in formatted


def test_format_omni_context_slices_empty() -> None:
    """Verify formatting empty slices list returns empty string."""
    assert format_omni_context_slices([]) == ""
