"""Unit tests for Safe File-Descriptor and Query-File IPC Pipeline.

[POS]
Verifies 0600 file permission enforcement, zero-trace shredding upon exit,
strict prohibition of shell -c and inline prompt string injections, and unadulterated
multiline/quote IPC delivery.
"""

from __future__ import annotations

import os
import sys

import pytest

from myrm_agent_harness.core.security.ipc import (
    IpcPayloadTransport,
    SafeIpcPipeline,
    SecureIpcFile,
    ShellArgumentInjectionError,
    read_query_file,
)


def test_secure_ipc_file_lifecycle_and_mode() -> None:
    payload = "Complex payload with quotes: 'hello' and \"world\" and $ENV"
    captured_path: str | None = None

    with SecureIpcFile(payload) as file_path:
        captured_path = file_path
        assert os.path.exists(file_path)

        # Check POSIX 0600 permission mode
        file_mode = os.stat(file_path).st_mode & 0o777
        assert file_mode == 0o600

        # Read content via read_query_file
        content = read_query_file(file_path)
        assert content == payload

    # Context manager exit -> file must be shredded and unlinked
    assert captured_path is not None
    assert not os.path.exists(captured_path)


def test_pipeline_validates_command_safety() -> None:
    pipeline = SafeIpcPipeline()

    # 1. Shell wrapper rejection
    with pytest.raises(ShellArgumentInjectionError) as exc_info:
        pipeline.validate_command_safety(["bash", "-c", "echo 'injected'"])
    assert exc_info.value.flag == "-c"

    # 2. Prohibited inline prompt argument with quotes/newlines
    with pytest.raises(ShellArgumentInjectionError) as exc_info2:
        pipeline.validate_command_safety(["agent_cli", "chat", "-q", "hello\nworld'$(rm -rf /)"])
    assert exc_info2.value.flag == "-q"

    # 3. Safe command with clean flags is permitted
    pipeline.validate_command_safety([sys.executable, "-m", "json.tool"])


@pytest.mark.asyncio
async def test_execute_with_query_file_preserves_dangerous_characters() -> None:
    pipeline = SafeIpcPipeline()

    # Python one-liner that reads from the file passed via --query-file and prints it
    py_worker_script = (
        "import sys, pathlib; "
        "idx = sys.argv.index('--query-file'); "
        "content = pathlib.Path(sys.argv[idx + 1]).read_text(); "
        "print('RECEIVED:', content, end='')"
    )

    dangerous_payload = (
        "SELECT * FROM users WHERE name = 'O''Reilly';\n"
        "$(whoami) && `cat /etc/passwd`\n"
        "\"Double Quotes\" and 'Single Quotes' and \\\\ backslashes\n"
        "EOL"
    )

    cmd = [sys.executable, "-c", py_worker_script]
    res = await pipeline.execute_with_query_file(cmd, dangerous_payload, query_flag="--query-file")

    assert res.returncode == 0
    assert res.stdout == f"RECEIVED: {dangerous_payload}"
    assert res.query_file_path is not None
    # Verify temporary file has been completely shredded and unlinked
    assert not os.path.exists(res.query_file_path)


@pytest.mark.asyncio
async def test_execute_with_stdin_stream() -> None:
    pipeline = SafeIpcPipeline()

    # Python script reading stdin
    py_worker_script = "import sys; print(f'STDIN:{sys.stdin.read()}', end='')"
    payload = "Data stream with $VAR and 'quotes' across\nmultiple\nlines."

    cmd = [sys.executable, "-c", py_worker_script]
    res = await pipeline.dispatch(cmd, payload, transport=IpcPayloadTransport.STDIN_STREAM)

    assert res.returncode == 0
    assert res.stdout == f"STDIN:{payload}"
    assert res.duration_seconds >= 0.0


@pytest.mark.asyncio
async def test_execute_timeout_handling() -> None:
    pipeline = SafeIpcPipeline()

    # Sleep longer than timeout
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    res = await pipeline.execute_with_query_file(cmd, "test", timeout_seconds=0.2)

    assert res.returncode == -1
    assert "timed out" in res.stderr
