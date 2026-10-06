"""Unit tests for Two-Phase Hard Anchors + Soft Context Scoring Diff Protocol (Item 25)."""

import pytest

from myrm_agent_harness.runtime.context.diff_protocol_scorer import (
    DiffApplyResult,
    DiffOperation,
    DiffProtocolError,
    apply_diff_operation,
    apply_diff_patch,
    parse_diff_operations,
)


def test_hunk_ranges_ignored_and_context_indentation_preserved() -> None:
    """Verifies hunk range headers (@@ -400,2 +900,3 @@) are ignored and original indentation is preserved."""
    diff_text = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -400,2 +900,3 @@
     answer = 1
+    enabled = True
     return answer
"""
    ops, errors = parse_diff_operations(diff_text)
    assert not errors
    assert len(ops) == 1

    file_content = "        answer = 1\n        return answer\n"
    res: DiffApplyResult = apply_diff_operation(ops[0], file_content)
    expected = "        answer = 1\n    enabled = True\n        return answer\n"
    assert res.patched_content == expected
    assert res.hunks_applied == 1


def test_missing_context_line_matches_unique_hard_anchors() -> None:
    """Phase 1 locates the region via deletion (-) lines alone even if model omitted a context line."""
    file_content = (
        "def process_data(data):\n"
        "    if not data:\n"
        "        print('Error: No data provided')\n"
        "        logger.error('Data is missing')\n"
        "        return None\n"
        "    result = transform(data)\n"
        "    return result\n"
    )

    diff_text = """diff --git a/utils.py b/utils.py
--- a/utils.py
+++ b/utils.py
@@ -1,7 +1,5 @@
 def process_data(data):
     if not data:
-        print('Error: No data provided')
-        logger.error('Data is missing')
-        return None
+        raise ValueError('Data is missing')
     return result
"""
    res = apply_diff_patch(diff_text, file_content)
    assert "raise ValueError('Data is missing')" in res.patched_content
    assert "print('Error: No data provided')" not in res.patched_content
    assert "logger.error('Data is missing')" not in res.patched_content
    assert "result = transform(data)" in res.patched_content


def test_context_scoring_disambiguates_duplicated_remove_blocks() -> None:
    """Verifies soft context scoring disambiguates identical delete blocks based on context lines."""
    file_content = (
        "def process_alpha(data):\n"
        "    if not data:\n"
        "        print('Error')\n"
        "        return None\n"
        "    return alpha(data)\n"
        "\n"
        "def process_beta(data):\n"
        "    if not data:\n"
        "        print('Error')\n"
        "        return None\n"
        "    return beta(data)\n"
    )

    # Context specifies process_beta
    diff_text = """diff --git a/pipeline.py b/pipeline.py
--- a/pipeline.py
+++ b/pipeline.py
@@ -10,5 +10,4 @@
 def process_beta(data):
     if not data:
-        print('Error')
-        return None
+        raise RuntimeError('Beta failure')
     return beta(data)
"""
    res = apply_diff_patch(diff_text, file_content)
    # process_alpha retains print('Error')
    assert "def process_alpha(data):\n    if not data:\n        print('Error')" in res.patched_content
    # process_beta is updated
    assert "def process_beta(data):\n    if not data:\n        raise RuntimeError('Beta failure')" in res.patched_content


def test_ambiguous_tie_raises_diff_protocol_error_with_finding() -> None:
    """Verifies that when identical remove blocks tie on context score, application fails closed."""
    file_content = "TIMEOUT = 10\nTIMEOUT = 10\n"
    diff_text = """diff --git a/conf.py b/conf.py
--- a/conf.py
+++ b/conf.py
@@ -1,1 +1,1 @@
-TIMEOUT = 10
+TIMEOUT = 20
"""
    with pytest.raises(DiffProtocolError) as exc_info:
        apply_diff_patch(diff_text, file_content)

    err = exc_info.value
    assert "ambiguous" in str(err).lower()
    assert err.finding is not None
    assert err.finding.candidate_count == 2
    assert err.finding.tied_candidates == 2


def test_missing_hard_anchors_fails_closed() -> None:
    """Verifies when deleted lines do not exist, operation fails closed with PatchDriftFinding."""
    file_content = "def hello():\n    return 'hello'\n"
    diff_text = """diff --git a/hello.py b/hello.py
--- a/hello.py
+++ b/hello.py
@@ -1,2 +1,2 @@
-def missing_func():
-    return 'missing'
+def new_func():
+    return 'new'
"""
    with pytest.raises(DiffProtocolError) as exc_info:
        apply_diff_patch(diff_text, file_content)

    err = exc_info.value
    assert "not found verbatim" in str(err)
    assert err.finding is not None
    assert err.finding.candidate_count == 0


def test_pure_addition_creates_new_file() -> None:
    """Verifies creation diff from /dev/null generates new file content."""
    diff_text = """diff --git a/dev/null b/config.py
--- /dev/null
+++ b/config.py
@@ -0,0 +1,3 @@
+API_KEY = 'secret'
+DEBUG = True
+RETRIES = 3
"""
    res = apply_diff_patch(diff_text, "")
    assert res.is_created is True
    assert res.patched_content == "API_KEY = 'secret'\nDEBUG = True\nRETRIES = 3\n"


def test_pure_insertion_within_existing_file() -> None:
    """Verifies pure insertion with context lines inserts additions at the exact position."""
    file_content = "def setup():\n    init_logging()\n    init_db()\n"
    diff_text = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 def setup():
     init_logging()
+    init_telemetry()
     init_db()
"""
    res = apply_diff_patch(diff_text, file_content)
    expected = "def setup():\n    init_logging()\n    init_telemetry()\n    init_db()\n"
    assert res.patched_content == expected


def test_markdown_fence_bleed_protection() -> None:
    """Verifies closing code block fences bleeding into '+' lines on non-markdown files are stripped."""
    diff_text = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -1,2 +1,3 @@
 def start():
+    run_worker()
+```
"""
    ops, errors = parse_diff_operations(diff_text)
    assert not errors
    op: DiffOperation = ops[0]
    # Check that +``` was stripped from hunks
    for h in op.hunks:
        for line in h.lines:
            assert line.text != "```"


def test_multiple_hunks_applied_sequentially() -> None:
    """Verifies multiple hunks apply cleanly to evolving content."""
    file_content = "alpha\nbeta\ngamma\ndelta\n"
    diff_text = """diff --git a/items.txt b/items.txt
--- a/items.txt
+++ b/items.txt
@@ -1,1 +1,1 @@
-alpha
+ALPHA
@@ -4,1 +4,1 @@
-delta
+DELTA
"""
    res = apply_diff_patch(diff_text, file_content)
    assert res.patched_content == "ALPHA\nbeta\ngamma\nDELTA\n"
    assert res.hunks_applied == 2
