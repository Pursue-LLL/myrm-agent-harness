"""Chunked, byte-exact file transfer over a shell-only executor.

Executors that implement just ``execute_bash`` inherit file operations built on this module.
Shell output passes through ``ExecutionResult`` which truncates and scrubs stdout, so file bytes
are never read as raw text: they are read as hex, which the scrubber cannot alter. Writes carry
base64 on the command line, so each command stays far below the per-argument limit (128 KB on Linux).

[INPUT]
- toolkits.code_execution.executors.models::ExecutionResult (POS: Result of one shell command.)

[OUTPUT]
- read_bytes_via_shell: Read a whole file as exact bytes through chunked ``dd`` + ``od`` commands.
- write_bytes_via_shell: Write or append bytes through chunked ``base64 -d`` commands.

[POS]
Lossless file transfer primitives for ``CodeExecutor`` shell-based default file operations.
"""

import shlex
from base64 import b64encode
from collections.abc import Awaitable, Callable
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult

__all__ = ["read_bytes_via_shell", "write_bytes_via_shell"]

ExecBash = Callable[[str], Awaitable[ExecutionResult]]

# 32 KiB raw -> ~44 KB base64 per write command and ~64 KB hex per read result,
# well under the 128 KB argument limit and the 200K-char stdout cap.
CHUNK_BYTES = 32 * 1024


async def read_bytes_via_shell(exec_bash: ExecBash, safe_path: str, display_path: str) -> bytes:
    """Read ``safe_path`` byte-exactly. Files below one chunk need a single command."""
    first = await _read_chunk(exec_bash, safe_path, 0, display_path)
    if len(first) < CHUNK_BYTES:
        return first

    size_result = await exec_bash(f"wc -c < {shlex.quote(safe_path)}")
    if not size_result.success:
        raise OSError(f"Cannot read '{display_path}': {size_result.error or size_result.stderr}")
    total = int(size_result.stdout.strip())

    parts = [first]
    for index in range(1, -(-total // CHUNK_BYTES)):
        parts.append(await _read_chunk(exec_bash, safe_path, index, display_path))
    data = b"".join(parts)
    if len(data) != total:
        raise OSError(f"Short read of '{display_path}': expected {total} bytes, got {len(data)}")
    return data


async def _read_chunk(exec_bash: ExecBash, safe_path: str, index: int, display_path: str) -> bytes:
    quoted = shlex.quote(safe_path)
    # `test -f` makes a missing or non-regular file fail the whole pipeline (a pipeline reports only its last stage).
    result = await exec_bash(
        f"test -f {quoted} && dd if={quoted} bs={CHUNK_BYTES} skip={index} count=1 2>/dev/null"
        " | od -An -v -tx1 | tr -d ' \\n'"
    )
    if not result.success:
        error = f"Cannot read '{display_path}': {result.error or result.stderr}"
        raise FileNotFoundError(error) if index == 0 else OSError(error)
    return bytes.fromhex(result.stdout)


async def write_bytes_via_shell(
    exec_bash: ExecBash, safe_path: str, display_path: str, content: bytes, *, append: bool = False
) -> None:
    """Write (truncating) or append ``content``; parent directories are created for writes."""
    quoted = shlex.quote(safe_path)
    chunks = [content[start : start + CHUNK_BYTES] for start in range(0, len(content), CHUNK_BYTES)] or [b""]
    for index, chunk in enumerate(chunks):
        truncating = index == 0 and not append
        prefix = f"mkdir -p {shlex.quote(str(Path(safe_path).parent))} && " if truncating else ""
        redirect = ">" if truncating else ">>"
        result = await exec_bash(f"{prefix}printf %s '{b64encode(chunk).decode()}' | base64 -d {redirect} {quoted}")
        if not result.success:
            raise OSError(f"Cannot write '{display_path}': {result.error or result.stderr}")
