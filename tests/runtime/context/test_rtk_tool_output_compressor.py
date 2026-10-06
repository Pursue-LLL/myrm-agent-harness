"""Unit tests for RTK Command-Aware Tool Output Lossless Compressor.

Covers:
1. Pytest/test failure extraction and passing test folding
2. Build compilation fatal error localization and file line mapping
3. Code search result capping and affected file aggregation
4. Git patch application failure and conflict hunk extraction
5. Bounded diagnostic windows for oversized generic shell execution
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.rtk_tool_compressor_types import (
    RTKCompressorConfig,
    ToolCommandType,
)
from myrm_agent_harness.runtime.context.rtk_tool_output_compressor import (
    RTKCommandAwareToolOutputCompressor,
)


def test_pytest_failure_extraction_and_folding() -> None:
    """Verify failed test cases and tracebacks are extracted while verbose passes are folded."""
    compressor = RTKCommandAwareToolOutputCompressor()

    passing_noise = "\n".join(
        f"tests/unit/test_module_{i}.py . [ {i}%]" for i in range(1, 40)
    )
    raw_output = (
        f"{passing_noise}\n"
        "=================================== FAILURES ===================================\n"
        "______________________________ test_user_authentication ________________________\n"
        "    def test_user_authentication():\n"
        "        token = auth_service.generate_token(user)\n"
        ">       assert token.is_valid is True\n"
        "E       AssertionError: assert False is True\n"
        "tests/unit/test_auth.py:48: AssertionError\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/unit/test_auth.py::test_user_authentication - AssertionError: assert False is True\n"
        "======================== 1 failed, 39 passed in 4.12s ========================\n"
    )

    diagnosis = compressor.compress_tool_output(
        command="pytest -v tests/",
        raw_output=raw_output,
        exit_code=1,
    )

    assert diagnosis.command_type == ToolCommandType.TEST_EXECUTION
    assert diagnosis.exit_code == 1
    assert "tests/unit/test_auth.py" in diagnosis.affected_files
    assert any("AssertionError" in err for err in diagnosis.fatal_errors)
    assert "1 failed, 39 passed in 4.12s" in diagnosis.compressed_output
    # Passing dots should be folded
    assert "test_module_1.py" not in diagnosis.compressed_output
    assert diagnosis.compression_ratio > 0.30


def test_build_compilation_error_extraction() -> None:
    """Verify first fatal compiler errors and affected line numbers are extracted."""
    compressor = RTKCommandAwareToolOutputCompressor()

    compiler_output = (
        "[1/15] Compiling src/core/config.ts...\n"
        "[2/15] Compiling src/models/user.ts...\n"
        "src/models/user.ts:88:15 - error TS2322: Type 'string' is not assignable to type 'number'.\n"
        "  88     this.id = payload.id;\n"
        "                   ~~~~~~~~~~\n"
        "[3/15] Compiling src/routes/auth.ts...\n"
        "src/routes/auth.ts:12:5 - error TS2304: Cannot find name 'SessionManager'.\n"
        "Found 2 errors in 2 files.\n"
    )

    diagnosis = compressor.compress_tool_output(
        command="tsc --project tsconfig.json",
        raw_output=compiler_output,
        exit_code=2,
    )

    assert diagnosis.command_type == ToolCommandType.BUILD_COMPILATION
    assert diagnosis.exit_code == 2
    assert "src/models/user.ts" in diagnosis.affected_files
    assert any("error TS2322" in err for err in diagnosis.fatal_errors)
    assert "Found 2 errors in 2 files" in diagnosis.compressed_output


def test_code_search_capping_and_file_aggregation() -> None:
    """Verify code search matches are summarized cleanly and excessive matches capped."""
    compressor = RTKCommandAwareToolOutputCompressor()

    # Generate 60 search matches
    search_lines = [
        f"src/handlers/user_{i}.py:42:    logger.info('Processing user request')"
        for i in range(60)
    ]
    raw_search = "\n".join(search_lines)

    diagnosis = compressor.compress_tool_output(
        command="grep -rn 'logger.info' src/",
        raw_output=raw_search,
        exit_code=0,
    )

    assert diagnosis.command_type == ToolCommandType.CODE_SEARCH
    assert diagnosis.exit_code == 0
    assert "Total search matches: 60" in diagnosis.compressed_output
    assert "additional search matches truncated for brevity" in diagnosis.compressed_output
    assert len(diagnosis.affected_files) <= 40
    assert "src/handlers/user_0.py" in diagnosis.affected_files


def test_git_patch_conflict_extraction() -> None:
    """Verify failed git apply hunks and conflict files are localized."""
    compressor = RTKCommandAwareToolOutputCompressor()

    patch_output = (
        "Checking patch src/runtime/engine.py...\n"
        "error: while searching for:\n"
        "    def run_step(self):\n"
        "        pass\n"
        "error: patch failed: src/runtime/engine.py:102\n"
        "error: src/runtime/engine.py: patch does not apply\n"
        "Checking patch src/utils/helpers.py...\n"
        "Hunk #1 succeeded at 45.\n"
    )

    diagnosis = compressor.compress_tool_output(
        command="git apply fix_bug.patch",
        raw_output=patch_output,
        exit_code=1,
    )

    assert diagnosis.command_type == ToolCommandType.GIT_PATCH
    assert diagnosis.exit_code == 1
    assert "src/runtime/engine.py" in diagnosis.affected_files
    assert any("patch failed:" in err for err in diagnosis.fatal_errors)
    assert "patch does not apply" in diagnosis.compressed_output


def test_bounded_diagnostic_window_generic_shell() -> None:
    """Verify large stdout shell output is bounded with head-tail preservation."""
    config = RTKCompressorConfig(
        max_output_chars=800,
        head_window_lines=10,
        tail_window_lines=15,
    )
    compressor = RTKCommandAwareToolOutputCompressor(config=config)

    long_lines = [f"Step {i}: executing database migration batch {i}" for i in range(200)]
    long_output = "\n".join(long_lines)

    diagnosis = compressor.compress_tool_output(
        command="bash run_long_migrations.sh",
        raw_output=long_output,
        exit_code=0,
    )

    assert diagnosis.command_type == ToolCommandType.GENERIC_SHELL
    assert diagnosis.exit_code == 0
    assert "[... Omitted" in diagnosis.compressed_output
    assert "Step 0:" in diagnosis.compressed_output
    assert "Step 199:" in diagnosis.compressed_output
    assert len(diagnosis.compressed_output) < len(long_output)
    assert diagnosis.compression_ratio > 0.50
