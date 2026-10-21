"""Unit tests for semantic-aware diff with ref-ID normalization."""

import re


def test_ref_prefix_regex():
    """Test _REF_PREFIX_RE correctly matches ref ID prefixes."""
    from myrm_agent_harness.toolkits.browser.session.snapshot_manager import _REF_PREFIX_RE

    test_cases = [
        ("e0: button 'Submit'", True, " button 'Submit'"),
        ("e123: link 'Home'", True, " link 'Home'"),
        ("f1_e0: button 'Click'", True, " button 'Click'"),
        ("f2_e456: textbox 'Search'", True, " textbox 'Search'"),
        ("e0 button 'Submit'", True, "button 'Submit'"),
        ("  e0: indented", False, "  e0: indented"),
        ("button 'Submit'", False, "button 'Submit'"),
    ]

    for line, should_match, expected_after_sub in test_cases:
        match = _REF_PREFIX_RE.match(line)
        assert (match is not None) == should_match, f"Failed for: {line}"

        result = _REF_PREFIX_RE.sub("", line)
        assert result == expected_after_sub, f"Expected '{expected_after_sub}', got '{result}'"

    print(" _REF_PREFIX_RE regex working correctly")


def test_semantic_diff_immune_to_ref_renumbering():
    """Test that diff is immune to ref ID renumbering."""
    import difflib

    ref_prefix_re = re.compile(r"^(?:f\d+_)?e\d+[:\s]")

    prev_tree = """e0: button 'Submit'
e1: link 'Home'
e2: textbox 'Search'"""

    current_tree = """e10: button 'Submit'
e11: link 'Home'
e12: textbox 'Search'"""

    prev_normalized = [ref_prefix_re.sub("", line) for line in prev_tree.split("\n")]
    current_normalized = [ref_prefix_re.sub("", line) for line in current_tree.split("\n")]

    assert prev_normalized == current_normalized

    matcher = difflib.SequenceMatcher(None, prev_normalized, current_normalized)
    opcodes = matcher.get_opcodes()

    assert len(opcodes) == 1
    assert opcodes[0][0] == "equal"

    print(" Diff immune to ref ID renumbering")


def test_semantic_diff_detects_content_changes():
    """Test that diff detects actual content changes."""
    import difflib

    ref_prefix_re = re.compile(r"^(?:f\d+_)?e\d+[:\s]")

    prev_tree = """e0: button 'Submit'
e1: link 'Home'
e2: textbox 'Search'"""

    current_tree = """e0: button 'Submit'
e1: link 'About'
e2: textbox 'Search'"""

    prev_normalized = [ref_prefix_re.sub("", line) for line in prev_tree.split("\n")]
    current_normalized = [ref_prefix_re.sub("", line) for line in current_tree.split("\n")]

    assert prev_normalized != current_normalized

    matcher = difflib.SequenceMatcher(None, prev_normalized, current_normalized)
    opcodes = matcher.get_opcodes()

    has_change = any(tag in ("replace", "delete", "insert") for tag, *_ in opcodes)
    assert has_change

    print(" Diff detects content changes")


def test_semantic_diff_with_iframe_refs():
    """Test that diff handles iframe ref prefixes (f1_e0)."""
    import difflib

    ref_prefix_re = re.compile(r"^(?:f\d+_)?e\d+[:\s]")

    prev_tree = """e0: button 'Main'
f1_e0: button 'IFrame Button'
f1_e1: link 'IFrame Link'"""

    current_tree = """e100: button 'Main'
f1_e200: button 'IFrame Button'
f1_e201: link 'IFrame Link'"""

    prev_normalized = [ref_prefix_re.sub("", line) for line in prev_tree.split("\n")]
    current_normalized = [ref_prefix_re.sub("", line) for line in current_tree.split("\n")]

    assert prev_normalized == current_normalized

    matcher = difflib.SequenceMatcher(None, prev_normalized, current_normalized)
    opcodes = matcher.get_opcodes()

    assert len(opcodes) == 1
    assert opcodes[0][0] == "equal"

    print(" Diff handles iframe ref prefixes correctly")


def test_diff_output_format():
    """Test that diff output uses +/- format."""
    from unittest.mock import MagicMock

    from myrm_agent_harness.toolkits.browser.session.snapshot_manager import SnapshotManager
    from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo

    manager = SnapshotManager(MagicMock())

    prev_tree = "e0: button 'Old'"
    prev_refs = {"e0": RefInfo(role="button", name="Old", nth=None)}
    manager._diff.update_baseline(prev_tree, prev_refs)

    current_tree = "e0: button 'New'"
    current_refs = {"e0": RefInfo(role="button", name="New", nth=None)}

    diff_output = manager._diff.generate_diff(current_tree, current_refs, max_tokens=0, chars_per_token=4)

    assert "--- Snapshot diff ---" in diff_output
    assert "- " in diff_output
    assert "+ " in diff_output
    assert "Old" in diff_output
    assert "New" in diff_output

    print(" Diff output format correct (+/-/space)")
    print(f"\nDiff output:\n{diff_output}")


if __name__ == "__main__":
    test_ref_prefix_regex()
    test_semantic_diff_immune_to_ref_renumbering()
    test_semantic_diff_detects_content_changes()
    test_semantic_diff_with_iframe_refs()
    test_diff_output_format()
    print("\n All semantic diff tests passed")
