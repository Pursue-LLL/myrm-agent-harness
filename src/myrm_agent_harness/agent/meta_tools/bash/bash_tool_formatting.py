"""Bash tool output formatting and truncation.

[INPUT]
- .bash_tool_exit_semantics::interpret_exit_code (POS: Exit-code semantic notes)
- output_compressor::compress_output (POS: Command-aware semantic output compressor)
- utils.context_format::wrap_with_tool_output_tag (POS: Tool output tag wrapping)

[OUTPUT]
- truncate_bash_output, format_result

[POS]
Formats BashExecutor results for LLM consumption with compression and redaction.
"""

from __future__ import annotations

from collections.abc import Mapping

from myrm_agent_harness.agent.meta_tools.bash.bash_tool_exit_semantics import interpret_exit_code


def truncate_bash_output(output: str, max_chars: int = 8000) -> tuple[str, bool, dict[str, object]]:
    """Smart middle-truncation for bash output to preserve errors at the end."""
    if len(output) <= max_chars:
        return output, False, {}
    half = max_chars // 2
    head = output[:half]
    tail = output[-half:]
    skipped = len(output) - max_chars

    total_lines = output.count("\n") + 1
    total_mb = len(output.encode("utf-8", errors="ignore")) / (1024 * 1024)

    hint = f"[ SYSTEM WARNING: Output is extremely large ({total_mb:.2f}MB, {total_lines} lines). Middle truncated: {skipped} chars skipped. Redirect to a file with > file.txt, then use file_read_tool to read specific sections.]"

    meta = {
        "type": "bash",
        "total_lines": total_lines,
        "total_mb": round(total_mb, 2),
        "shown_chars": max_chars,
    }

    return f"{head}\n\n...{hint}...\n\n{tail}", True, meta


def format_result(result: Mapping[str, object], command: str = "") -> tuple[str, bool, dict[str, object]]:
    """Format execution result with exit code semantic annotations."""
    from myrm_agent_harness.utils.context_format import wrap_with_tool_output_tag

    stdout_raw = str(result.get("stdout", ""))
    exit_code = str(result.get("exit_code", "0"))

    if stdout_raw and command:
        from myrm_agent_harness.agent.meta_tools.bash.output_compressor import (
            compress_output,
        )

        workspace_root = str(result.get("workspace_root") or "") or None
        stdout_raw = compress_output(
            command,
            stdout_raw,
            exit_code=exit_code,
            workspace_root=workspace_root,
        )

    stdout_str, stdout_trunc, stdout_meta = truncate_bash_output(stdout_raw)
    stderr_str, stderr_trunc, stderr_meta = truncate_bash_output(str(result.get("stderr", "")))

    output_parts: list[str] = []

    if stdout_str:
        output_parts.append(stdout_str)

    if stderr_str:
        output_parts.append(f"[stderr]\n{stderr_str}")

    if exit_code != "0":
        try:
            code_int = int(exit_code)
        except ValueError:
            code_int = -1
        meaning = interpret_exit_code(command, code_int) if command else None
        if meaning:
            output_parts.append(f"[exit_code: {exit_code} — {meaning}]")
        else:
            output_parts.append(f"[exit_code: {exit_code}]")

    if not output_parts:
        return "(no output)", False, {}

    formatted = "\n".join(output_parts)

    from myrm_agent_harness.utils.text_utils import sanitize_binary_output, strip_ansi

    formatted = strip_ansi(formatted)
    formatted = sanitize_binary_output(formatted)

    from myrm_agent_harness.agent.security.redact import redact_sensitive_text

    formatted = redact_sensitive_text(formatted)

    is_truncated = stdout_trunc or stderr_trunc
    meta = stdout_meta if stdout_trunc else (stderr_meta if stderr_trunc else {})

    return wrap_with_tool_output_tag(formatted), is_truncated, meta
