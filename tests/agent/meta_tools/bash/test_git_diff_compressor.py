from myrm_agent_harness.agent.meta_tools.bash.output_compressor import GitDiffCompressor


def test_git_diff_compressor_truncates_long_hunks():
    compressor = GitDiffCompressor()

    # Create a mock diff with a very long hunk
    lines = [
        "diff --git a/test.txt b/test.txt",
        "index 123..456 100644",
        "--- a/test.txt",
        "+++ b/test.txt",
        "@@ -1,5 +1,150 @@",
    ]

    # Add 150 lines of additions
    for i in range(150):
        lines.append(f"+ line {i}")

    lines.append("diff --git a/other.txt b/other.txt")
    lines.append("@@ -1,2 +1,2 @@")
    lines.append("+ other line")

    raw_output = "\n".join(lines)

    compressed = compressor.compress(raw_output)

    assert compressed is not None
    assert "diff --git a/test.txt b/test.txt" in compressed
    assert "@@ -1,5 +1,150 @@" in compressed

    # Should contain exactly 100 lines of the first hunk
    assert "+ line 0" in compressed
    assert "+ line 99" in compressed
    assert "+ line 100" not in compressed

    # Should contain the truncation message with dynamic filename and neutral prompt
    assert "[System Note: ... (50 lines hidden in test.txt) ...]" in compressed

    # Should contain the second file and its hunk
    assert "diff --git a/other.txt b/other.txt" in compressed
    assert "@@ -1,2 +1,2 @@" in compressed
    assert "+ other line" in compressed


def test_git_diff_compressor_keeps_short_hunks():
    compressor = GitDiffCompressor()

    lines = [
        "diff --git a/test.txt b/test.txt",
        "@@ -1,5 +1,10 @@",
    ]
    for i in range(10):
        lines.append(f"+ line {i}")

    raw_output = "\n".join(lines)
    compressed = compressor.compress(raw_output)

    # It shouldn't compress because it's not long enough to save 10%
    assert compressed is None
