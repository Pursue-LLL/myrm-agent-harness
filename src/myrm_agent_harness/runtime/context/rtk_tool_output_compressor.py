"""RTK Command-Aware Tool Output Lossless Compressor.

Implements lossless-first compression for test failures, compiler errors,
git patch conflicts, and code searches with bounded diagnostic windows.

[INPUT]
- runtime.context.rtk_tool_compressor_types::ExtractedDiagnosis, RTKCompressorConfig, ToolCommandType (POS:
  Strongly typed data contracts for RTK Command-Aware Tool Output Lossless Compressor.)

[OUTPUT]
- RTKCommandAwareToolOutputCompressor: Zero-LLM structure-preserving tool result extractor and compressor.

[POS]
RTK Command-Aware Tool Output Lossless Compressor.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.rtk_tool_compressor_types import (
    ExtractedDiagnosis,
    RTKCompressorConfig,
    ToolCommandType,
)


class RTKCommandAwareToolOutputCompressor:
    """Zero-LLM structure-preserving tool result extractor and compressor."""

    TEST_CMD_PATTERN: re.Pattern[str] = re.compile(
        r"\b(?:pytest|vitest|jest|cargo\s+test|go\s+test|npm\s+test)\b", re.IGNORECASE
    )
    BUILD_CMD_PATTERN: re.Pattern[str] = re.compile(
        r"\b(?:tsc|cargo\s+build|gcc|g\+\+|webpack|vite\s+build|esbuild|make)\b",
        re.IGNORECASE,
    )
    SEARCH_CMD_PATTERN: re.Pattern[str] = re.compile(
        r"\b(?:grep|rg|ripgrep|find|glob)\b", re.IGNORECASE
    )
    GIT_PATCH_PATTERN: re.Pattern[str] = re.compile(
        r"\bgit\s+(?:apply|patch|merge|rebase|cherry-pick)\b", re.IGNORECASE
    )

    def __init__(self, config: RTKCompressorConfig | None = None) -> None:
        self.config = config or RTKCompressorConfig()

    def detect_command_type(self, command_line: str, output: str) -> ToolCommandType:
        """Infer command type from invocation string or distinctive output markers."""
        cmd = command_line.strip()
        if self.TEST_CMD_PATTERN.search(cmd):
            return ToolCommandType.TEST_EXECUTION
        if self.BUILD_CMD_PATTERN.search(cmd):
            return ToolCommandType.BUILD_COMPILATION
        if self.SEARCH_CMD_PATTERN.search(cmd):
            return ToolCommandType.CODE_SEARCH
        if self.GIT_PATCH_PATTERN.search(cmd):
            return ToolCommandType.GIT_PATCH

        # Fallback to output heuristics
        if "=== FAILURES ===" in output or "FAILED tests/" in output:
            return ToolCommandType.TEST_EXECUTION
        if "error TS" in output or "error[E" in output or "fatal error:" in output:
            return ToolCommandType.BUILD_COMPILATION
        if "patch failed:" in output or "CONFLICT (" in output:
            return ToolCommandType.GIT_PATCH

        return ToolCommandType.GENERIC_SHELL

    def compress_tool_output(
        self,
        command: str,
        raw_output: str,
        exit_code: int | None = None,
    ) -> ExtractedDiagnosis:
        """Compress output using a command-aware lossless strategy."""
        orig_len = len(raw_output)
        cmd_type = self.detect_command_type(command, raw_output)

        if cmd_type == ToolCommandType.TEST_EXECUTION:
            diagnosis = self._extract_test_failures(command, raw_output, exit_code)
        elif cmd_type == ToolCommandType.BUILD_COMPILATION:
            diagnosis = self._extract_build_errors(command, raw_output, exit_code)
        elif cmd_type == ToolCommandType.CODE_SEARCH:
            diagnosis = self._extract_search_results(command, raw_output, exit_code)
        elif cmd_type == ToolCommandType.GIT_PATCH:
            diagnosis = self._extract_git_patch_conflicts(command, raw_output, exit_code)
        else:
            diagnosis = self._extract_generic_shell(command, raw_output, exit_code)

        # Enforce maximum character boundary via bounded diagnostic window if necessary
        compressed_text = diagnosis.compressed_output
        if len(compressed_text) > self.config.max_output_chars:
            compressed_text = self._apply_bounded_window(compressed_text.splitlines())

        comp_len = len(compressed_text)
        ratio = round((orig_len - comp_len) / orig_len, 4) if orig_len > 0 else 0.0

        return ExtractedDiagnosis(
            command_type=cmd_type,
            exit_code=exit_code,
            fatal_errors=diagnosis.fatal_errors,
            summary=diagnosis.summary,
            compressed_output=compressed_text,
            original_chars=orig_len,
            compressed_chars=comp_len,
            compression_ratio=max(0.0, ratio),
            reproducible_command=command,
            affected_files=diagnosis.affected_files,
        )

    def _extract_test_failures(
        self,
        command: str,
        output: str,
        exit_code: int | None,
    ) -> ExtractedDiagnosis:
        """Extract failed tests, failure assertions, and summary lines."""
        lines = output.splitlines()
        extracted: list[str] = [f"Command: {command}", f"Exit Code: {exit_code}\n"]
        fatal_errors: list[str] = []
        affected_files: set[str] = set()

        in_failure_section = False
        summary_lines: list[str] = []

        for line in lines:
            trimmed = line.strip()
            # Detect summary line
            if re.search(r"=\s*(\d+\s+failed|\d+\s+passed|\d+\s+error).*", trimmed):
                summary_lines.append(trimmed)

            if "FAILURES" in line or "FAILED " in line:
                in_failure_section = True
                if "FAILED " in line:
                    fatal_errors.append(trimmed)
                    file_match = re.search(r"FAILED\s+([^\s:]+)", trimmed)
                    if file_match:
                        affected_files.add(file_match.group(1))

            if in_failure_section:
                extracted.append(line)
                if "AssertionError:" in line or "Error:" in line:
                    fatal_errors.append(trimmed)

        if not fatal_errors and summary_lines:
            # All tests passed or no failures found
            extracted.extend(summary_lines)
            summary = summary_lines[-1] if summary_lines else "Tests completed."
        else:
            summary = f"Detected {len(fatal_errors)} test failure marker(s)."
            extracted.extend(summary_lines)

        return ExtractedDiagnosis(
            command_type=ToolCommandType.TEST_EXECUTION,
            exit_code=exit_code,
            fatal_errors=tuple(fatal_errors[:10]),
            summary=summary,
            compressed_output="\n".join(extracted),
            original_chars=len(output),
            compressed_chars=0,
            compression_ratio=0.0,
            affected_files=tuple(sorted(affected_files)),
        )

    def _extract_build_errors(
        self,
        command: str,
        output: str,
        exit_code: int | None,
    ) -> ExtractedDiagnosis:
        """Extract first fatal build error and relevant line numbers."""
        lines = output.splitlines()
        extracted: list[str] = [f"Command: {command}", f"Exit Code: {exit_code}\n"]
        fatal_errors: list[str] = []
        affected_files: set[str] = set()

        for line in lines:
            trimmed = line.strip()
            # Match TypeScript, Rust, GCC, or generic error lines
            if re.search(r"(error\s+TS\d+|error\[E\d+\]|fatal\s+error:|:\s*error:)", trimmed, re.IGNORECASE):
                fatal_errors.append(trimmed)
                extracted.append(line)
                file_match = re.search(r"([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+)[:(]\d+", trimmed)
                if file_match:
                    affected_files.add(file_match.group(1))
            elif fatal_errors and len(extracted) < 30:
                # Keep snippet context following the error
                extracted.append(line)

        summary = (
            f"Build failed with {len(fatal_errors)} fatal error(s)."
            if fatal_errors
            else "Build command completed."
        )

        return ExtractedDiagnosis(
            command_type=ToolCommandType.BUILD_COMPILATION,
            exit_code=exit_code,
            fatal_errors=tuple(fatal_errors[:5]),
            summary=summary,
            compressed_output="\n".join(extracted) if fatal_errors else output[:1000],
            original_chars=len(output),
            compressed_chars=0,
            compression_ratio=0.0,
            affected_files=tuple(sorted(affected_files)),
        )

    def _extract_search_results(
        self,
        command: str,
        output: str,
        exit_code: int | None,
    ) -> ExtractedDiagnosis:
        """Extract clean code search matches, capping unbounded results."""
        lines = [line for line in output.splitlines() if line.strip()]
        max_matches = 40
        retained = lines[:max_matches]
        omitted = len(lines) - len(retained)

        header = f"Command: {command}\nTotal search matches: {len(lines)}\n"
        if omitted > 0:
            retained.append(f"\n[... {omitted} additional search matches truncated for brevity ...]")

        affected_files: set[str] = set()
        for line in retained:
            file_match = re.match(r"^([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+):", line)
            if file_match:
                affected_files.add(file_match.group(1))

        return ExtractedDiagnosis(
            command_type=ToolCommandType.CODE_SEARCH,
            exit_code=exit_code,
            fatal_errors=(),
            summary=f"Found {len(lines)} search matches across {len(affected_files)} file(s).",
            compressed_output=header + "\n".join(retained),
            original_chars=len(output),
            compressed_chars=0,
            compression_ratio=0.0,
            affected_files=tuple(sorted(affected_files)),
        )

    def _extract_git_patch_conflicts(
        self,
        command: str,
        output: str,
        exit_code: int | None,
    ) -> ExtractedDiagnosis:
        """Extract failed patch hunks and contested filenames."""
        lines = output.splitlines()
        extracted: list[str] = [f"Command: {command}", f"Exit Code: {exit_code}\n"]
        fatal_errors: list[str] = []
        affected_files: set[str] = set()

        for line in lines:
            trimmed = line.strip()
            if "patch failed:" in trimmed or "CONFLICT (" in trimmed or "error:" in trimmed:
                fatal_errors.append(trimmed)
                extracted.append(line)
                file_match = re.search(r"(?:patch\s+failed:\s*|Merge\s+conflict\s+in\s*)([^\s:]+)", trimmed)
                if file_match:
                    affected_files.add(file_match.group(1))
            elif any(k in trimmed for k in ("Hunk #", "rejected", "does not apply")):
                extracted.append(line)

        summary = f"Git operation failed on {len(affected_files)} file(s)."

        return ExtractedDiagnosis(
            command_type=ToolCommandType.GIT_PATCH,
            exit_code=exit_code,
            fatal_errors=tuple(fatal_errors),
            summary=summary,
            compressed_output="\n".join(extracted),
            original_chars=len(output),
            compressed_chars=0,
            compression_ratio=0.0,
            affected_files=tuple(sorted(affected_files)),
        )

    def _extract_generic_shell(
        self,
        command: str,
        output: str,
        exit_code: int | None,
    ) -> ExtractedDiagnosis:
        """Fallback for general shell execution with bounded diagnostics."""
        lines = output.splitlines()
        compressed_text = self._apply_bounded_window(lines)
        header = f"Command: {command}\nExit Code: {exit_code}\n\n"

        fatal_errors: list[str] = []
        for line in lines[-10:]:
            if "error" in line.lower() or "exception" in line.lower():
                fatal_errors.append(line.strip())

        return ExtractedDiagnosis(
            command_type=ToolCommandType.GENERIC_SHELL,
            exit_code=exit_code,
            fatal_errors=tuple(fatal_errors),
            summary=f"Shell command exited with status {exit_code}.",
            compressed_output=header + compressed_text,
            original_chars=len(output),
            compressed_chars=0,
            compression_ratio=0.0,
            affected_files=(),
        )

    def _apply_bounded_window(self, lines: Sequence[str]) -> str:
        """Apply head-tail window around long outputs, folding the middle."""
        total = len(lines)
        head_count = self.config.head_window_lines
        tail_count = self.config.tail_window_lines

        if total <= (head_count + tail_count + 5):
            return "\n".join(lines)

        head_part = list(lines[:head_count])
        tail_part = list(lines[-tail_count:])
        omitted = total - head_count - tail_count

        return (
            "\n".join(head_part)
            + f"\n\n[... Omitted {omitted} lines of non-error output ...]\n\n"
            + "\n".join(tail_part)
        )
