"""Strongly typed data contracts for RTK Command-Aware Tool Output Lossless Compressor.

Provides enums, configuration classes, and extracted diagnosis payload models with zero Any.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ToolCommandType: Categorization of tool execution command types for lossless filtering.
- RTKCompressorConfig: Configuration for command-aware output filtering and bounded diagnostic windows.
- ExtractedDiagnosis: Structured extraction of critical diagnosis without losing precision.

[POS]
Strongly typed data contracts for RTK Command-Aware Tool Output Lossless Compressor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ToolCommandType(StrEnum):
    """Categorization of tool execution command types for lossless filtering."""

    TEST_EXECUTION = "test_execution"  # pytest, vitest, jest, cargo test, go test
    BUILD_COMPILATION = "build_compilation"  # tsc, cargo build, gcc, g++, webpack, vite
    CODE_SEARCH = "code_search"  # grep, rg, ripgrep, glob, find
    GIT_PATCH = "git_patch"  # git apply, git patch, git merge, git rebase
    GENERIC_SHELL = "generic_shell"  # Generic terminal commands


@dataclass(frozen=True)
class RTKCompressorConfig:
    """Configuration for command-aware output filtering and bounded diagnostic windows."""

    max_output_chars: int = 3000
    head_window_lines: int = 15
    tail_window_lines: int = 35
    fold_successful_tests: bool = True
    preserve_exit_code: bool = True


@dataclass(frozen=True)
class ExtractedDiagnosis:
    """Structured extraction of critical diagnosis without losing precision."""

    command_type: ToolCommandType
    exit_code: int | None
    fatal_errors: tuple[str, ...]
    summary: str
    compressed_output: str
    original_chars: int
    compressed_chars: int
    compression_ratio: float
    reproducible_command: str = ""
    affected_files: tuple[str, ...] = field(default_factory=tuple)
