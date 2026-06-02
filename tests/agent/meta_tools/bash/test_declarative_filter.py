from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.bash.output_compressor import (
    DeclarativeFilterEngine,
    compress_output,
)


def test_declarative_filter_engine_builtin_make():
    engine = DeclarativeFilterEngine()

    make_output = """make[1]: Entering directory '/home/user/project'
gcc -O2 -Wall -c foo.c -o foo.o
make[1]: Leaving directory '/home/user/project'
make[1]: Nothing to be done for 'all'.
"""

    # It should compress make output
    compressed = engine.compress("make all", make_output)

    assert compressed is not None
    assert "gcc -O2 -Wall -c foo.c -o foo.o" in compressed
    assert "Entering directory" not in compressed
    assert "Leaving directory" not in compressed
    assert "Nothing to be done" not in compressed


def test_declarative_filter_engine_builtin_terraform():
    engine = DeclarativeFilterEngine()

    tf_output = """Acquiring state lock. This may take a few moments...
Refreshing state... [id=vpc-123]
Refreshing state... [id=subnet-456]

Terraform will perform the following actions:
  + resource "aws_instance" "web" {
      + ami = "ami-123"
    }

Plan: 1 to add, 0 to change, 0 to destroyed.
Releasing state lock. This may take a few moments...
"""

    compressed = engine.compress("terraform plan", tf_output)

    assert compressed is not None
    assert "Terraform will perform the following actions:" in compressed
    assert "aws_instance" in compressed
    assert "Refreshing state" not in compressed
    assert "Acquiring state lock" not in compressed
    assert "Releasing state lock" not in compressed
    # Test regex replace
    assert "Plan: 1 to add, 0 to change, 0 to destroy" in compressed


def test_declarative_filter_engine_user_local(tmp_path, monkeypatch):
    # Change cwd to tmp_path to test local .myrm/filters.yaml
    monkeypatch.chdir(tmp_path)

    myrm_dir = tmp_path / ".myrm"
    myrm_dir.mkdir()

    filters_file = myrm_dir / "filters.yaml"
    filters_file.write_text(
        """
    filters:
      - name: "custom-tool"
        match_command: "^my-tool"
        strip_lines_matching:
          - '^\\[INFO\\]'
        on_empty: "Tool ran successfully."
"""
    )

    engine = DeclarativeFilterEngine()

    output = "[INFO] Loading configs...\n[INFO] Connecting to DB...\n[ERROR] Connection failed!"

    compressed = engine.compress("my-tool run", output, workspace_root=tmp_path)
    assert compressed == "[ERROR] Connection failed!"

    # Test on_empty
    empty_output = "[INFO] Loading configs...\n[INFO] Done."
    compressed_empty = engine.compress("my-tool run", empty_output, workspace_root=tmp_path)
    assert compressed_empty == "Tool ran successfully."


def test_e2e_workspace_filters_via_workspace_root(tmp_path: Path) -> None:
    myrm_dir = tmp_path / ".myrm"
    myrm_dir.mkdir()
    (myrm_dir / "filters.yaml").write_text(
        """
filters:
  - name: e2e-filter-run
    match_command: 'run\\.sh'
    replace:
      - pattern: 'E2E_MASK_TOKEN=\\w+'
        replacement: 'E2E_MASKED_VAL'
    strip_lines_matching:
      - '^E2E_DEBUG:'
""",
        encoding="utf-8",
    )
    raw = "E2E_BEGIN_LINE ok\nE2E_DEBUG: loading config\nE2E_MASK_TOKEN=12345abcdef\nE2E_FINISH_LINE ok\n"
    compressed = compress_output("bash run.sh", raw, workspace_root=tmp_path)
    assert "E2E_DEBUG:" not in compressed
    assert "E2E_MASKED_VAL" in compressed
    assert "E2E_BEGIN_LINE" in compressed
    assert "E2E_FINISH_LINE" in compressed


def test_format_result_applies_workspace_declarative_filter(tmp_path: Path) -> None:
    from myrm_agent_harness.agent.meta_tools.bash import bash_tool

    myrm_dir = tmp_path / ".myrm"
    myrm_dir.mkdir()
    (myrm_dir / "filters.yaml").write_text(
        """
filters:
  - name: e2e-filter-run
    match_command: 'run\\.sh'
    strip_lines_matching:
      - '^E2E_DEBUG:'
""",
        encoding="utf-8",
    )
    raw = "E2E_BEGIN_LINE ok\nE2E_DEBUG: stripped\nE2E_FINISH_LINE ok\n"
    result = {
        "stdout": raw,
        "stderr": "",
        "exit_code": "0",
        "workspace_root": str(tmp_path),
    }
    formatted, _, _ = bash_tool._format_result(result, "bash run.sh")
    assert "E2E_DEBUG:" not in formatted
    assert "E2E_BEGIN_LINE" in formatted


def test_declarative_filter_engine_builtin_rsync_on_empty():
    engine = DeclarativeFilterEngine()
    output = "sending incremental file list\n\n"
    compressed = engine.compress("rsync -av src/ dst/", output)
    assert compressed == "rsync completed successfully (no files transferred or all filtered)."


def test_declarative_filter_engine_builtin_docker_pull_max_lines():
    engine = DeclarativeFilterEngine()
    lines = ["Pulling fs layer\n"] * 30 + ["done\n"]
    output = "".join(lines)
    compressed = engine.compress("docker pull nginx", output)
    assert compressed is not None
    assert "Pulling fs layer" not in compressed
    assert len(compressed.splitlines()) <= 21


def test_local_filter_takes_priority_over_builtin(tmp_path: Path) -> None:
    myrm_dir = tmp_path / ".myrm"
    myrm_dir.mkdir()
    (myrm_dir / "filters.yaml").write_text(
        """
filters:
  - name: custom-make
    match_command: '^make'
    strip_lines_matching:
      - '^LOCAL_ONLY'
""",
        encoding="utf-8",
    )
    engine = DeclarativeFilterEngine()
    output = "LOCAL_ONLY noise\nkeep this line\n"
    compressed = engine.compress("make all", output, workspace_root=tmp_path)
    assert compressed == "keep this line"


def test_compress_output_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYRM_BASH_COMPRESSION", "0")
    noisy = "make[1]: Entering directory '/x'\nreal output\n"
    assert compress_output("make", noisy) == noisy


def test_semantic_compressor_blocks_declarative_fallback() -> None:
    git_status = "On branch main\nnothing to commit, working tree clean\n"
    result = compress_output("git status", git_status)
    assert result != git_status or "On branch" in result


def test_no_matching_filter_returns_original() -> None:
    raw = "totally unknown command output\nline2\n"
    assert compress_output("unknown-cmd-xyz", raw) == raw


def test_compress_output_integration():
    # Test that compress_output correctly routes to declarative engine
    # when semantic compressors don't match or don't compress

    make_output = "make[1]: Entering directory '/home'\ngcc foo.c\nmake[1]: Leaving directory '/home'"

    # "make" doesn't match any semantic compressor, should fall through to declarative
    compressed = compress_output("make", make_output)

    assert compressed == "gcc foo.c"
    assert "Entering directory" not in compressed
