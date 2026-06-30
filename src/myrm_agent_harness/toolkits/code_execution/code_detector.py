"""Code type detector for bash vs Python execution routing.

Detects whether user input is Python or Bash and extracts embedded Python from
``python -c`` commands. Framework-agnostic; consumed by BashExecutor and executors.

[INPUT]
- python_extractor::extract_python_from_bash (POS: quote-aware Python extraction)

[OUTPUT]
- CodeType: Python vs Bash enum
- CodeDetectionResult: detection outcome with extracted code
- CodeTypeDetector: detector class
- code_detector: module singleton

[POS]
Pure code analysis with zero agent/ runtime dependencies. Lives in toolkits
alongside python_extractor SSOT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from myrm_agent_harness.toolkits.code_execution.python_extractor import extract_python_from_bash


class CodeType(StrEnum):
    PYTHON = "python"
    BASH = "bash"


@dataclass
class CodeDetectionResult:
    code_type: CodeType
    extracted_code: str
    is_async: bool = False
    detection_reason: str = ""


class CodeTypeDetector:
    """Detect Python vs Bash and extract Python from ``python -c`` commands.

    Detection order:
    1. ``python -c`` → Python (quote-aware extract, raw fallback on failure)
    2. ``await`` keyword → async Python
    3. Multi-line Python syntax patterns
    4. Default → Bash
    """

    _RAW_PYTHON_C_RE = re.compile(r"python3?\s+-c\s+(.+)", re.DOTALL)

    PYTHON_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (r"^\s*def\s+\w+\s*\(", "function definition"),
        (r"^\s*class\s+\w+", "class definition"),
        (r"^\s*import\s+", "import statement"),
        (r"^\s*from\s+\w+\s+import", "from import statement"),
        (r"^\s*for\s+\w+\s+in\s+", "for loop"),
        (r"^\s*if\s+.+:\s*$", "if statement"),
        (r"^\s*while\s+.+:\s*$", "while loop"),
        (r"^\s*try:\s*$", "try statement"),
        (r"^\s*except\s*.*:\s*$", "except statement"),
        (r"^\s*with\s+.+:\s*$", "with statement"),
        (r"print\s*\(", "print call"),
        (r"\.append\s*\(", "list append"),
        (r"\.get\s*\(", "dict get"),
        (r"\s*=\s*\[", "list assignment"),
        (r"\s*=\s*\{", "dict assignment"),
        (r"asyncio\.run\s*\(", "asyncio.run"),
    ]

    MIN_LINES_FOR_MULTILINE_DETECTION = 3

    def detect(self, command: str) -> CodeDetectionResult:
        if self._is_python_command(command):
            extracted = self._extract_python_code_from_command(command)
            if extracted:
                return CodeDetectionResult(
                    code_type=CodeType.PYTHON,
                    extracted_code=extracted,
                    is_async=self._contains_await(extracted),
                    detection_reason="python -c command (extracted)",
                )
            raw_code = self._raw_extract_python_c(command)
            return CodeDetectionResult(
                code_type=CodeType.PYTHON,
                extracted_code=raw_code,
                is_async=self._contains_await(raw_code),
                detection_reason="python -c command (raw fallback after quote extraction failed)",
            )

        if self._contains_await(command):
            return CodeDetectionResult(
                code_type=CodeType.PYTHON,
                extracted_code=command,
                is_async=True,
                detection_reason="contains await keyword",
            )

        python_pattern = self._detect_python_pattern(command)
        if python_pattern:
            return CodeDetectionResult(
                code_type=CodeType.PYTHON,
                extracted_code=command,
                is_async=False,
                detection_reason=f"python syntax: {python_pattern}",
            )

        return CodeDetectionResult(
            code_type=CodeType.BASH,
            extracted_code=command,
            is_async=False,
            detection_reason="default to bash",
        )

    def _contains_await(self, command: str) -> bool:
        return bool(re.search(r"\bawait\b", command))

    def _is_python_command(self, command: str) -> bool:
        return bool(re.search(r"python3?\s+-c", command))

    def _extract_python_code_from_command(self, command: str) -> str | None:
        return extract_python_from_bash(command)

    def _raw_extract_python_c(self, command: str) -> str:
        match = self._RAW_PYTHON_C_RE.search(command)
        if not match:
            return command

        rest = match.group(1).strip()
        if len(rest) >= 2 and rest[0] in ("'", '"') and rest[-1] == rest[0]:
            return rest[1:-1]
        return rest

    def _detect_python_pattern(self, command: str) -> str | None:
        lines = [
            line.strip() for line in command.strip().split("\n") if line.strip() and not line.strip().startswith("#")
        ]

        if len(lines) <= self.MIN_LINES_FOR_MULTILINE_DETECTION:
            return None

        for pattern, name in self.PYTHON_PATTERNS:
            if re.search(pattern, command, re.MULTILINE):
                return name

        return None

    def is_python(self, command: str) -> bool:
        return self.detect(command).code_type == CodeType.PYTHON

    def is_bash(self, command: str) -> bool:
        return self.detect(command).code_type == CodeType.BASH


code_detector = CodeTypeDetector()
