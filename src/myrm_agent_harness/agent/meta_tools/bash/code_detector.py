"""代码类型检测器

检测代码类型（Python/Bash）并提取 Python 代码。
此模块不依赖 MCP 或其他业务逻辑，只负责代码类型检测。

[INPUT]
- skills.mcp.python_extractor::extract_python_from_bash (POS: Unified Python extraction with quote-aware parsing)

[OUTPUT]
- CodeType: class — Code Type
- CodeDetectionResult: class — Code Detection Result
- CodeTypeDetector: class — Code Type Detector

[POS]
Provides CodeType, CodeDetectionResult, CodeTypeDetector.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class CodeType(StrEnum):
    """代码类型"""

    PYTHON = "python"  # Python 代码
    BASH = "bash"  # Bash 命令


@dataclass
class CodeDetectionResult:
    """代码检测结果"""

    code_type: CodeType
    extracted_code: str  # 提取的代码（对于 python -c 命令，提取引号内的代码）
    is_async: bool = False  # 是否包含异步代码（await 关键字）
    detection_reason: str = ""  # 检测原因（用于日志）


class CodeTypeDetector:
    """代码类型检测器

    检测代码是 Python 还是 Bash，并提取 Python 代码。
    不依赖任何业务逻辑，只做纯粹的代码分析。

    检测顺序：
    1. python -c 命令 → Python
       - quote-aware 提取成功 → 用提取结果
       - 提取失败（如未配对引号）→ raw extraction（取 `-c` 后的所有内容），
         交由下游 `_validate_python_syntax` 给出语法错误诊断，
         **绝不**回退为 BASH 误执行（避免 shell 把 Python 源码当命令运行）。
    2. await 关键字 → Python（异步）
    3. Python 语法特征 → Python
    4. 默认 → Bash
    """

    # python -c 之后的原始内容捕获（quote-aware 提取失败时的兜底）
    _RAW_PYTHON_C_RE = re.compile(r"python3?\s+-c\s+(.+)", re.DOTALL)

    # Python 语法特征正则表达式
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

    # 最小行数阈值（用于多行代码检测）
    MIN_LINES_FOR_MULTILINE_DETECTION = 3

    def detect(self, command: str) -> CodeDetectionResult:
        """检测代码类型

        Args:
            command: 要检测的命令/代码

        Returns:
            CodeDetectionResult 检测结果
        """
        # 1. 检测 python -c 命令 — must precede await detection so that
        #    `python3 -c "...await..."` extracts the quoted code first.
        if self._is_python_command(command):
            extracted = self._extract_python_code_from_command(command)
            if extracted:
                return CodeDetectionResult(
                    code_type=CodeType.PYTHON,
                    extracted_code=extracted,
                    is_async=self._contains_await(extracted),
                    detection_reason="python -c command (extracted)",
                )
            # Quote-aware 提取失败时保留为 PYTHON 并用 raw extraction。
            # 让下游 ast.parse 报真实的 SyntaxError + python -c hint,
            # 而不是把含特殊字符的 Python 源码当 bash 命令误执行。
            raw_code = self._raw_extract_python_c(command)
            return CodeDetectionResult(
                code_type=CodeType.PYTHON,
                extracted_code=raw_code,
                is_async=self._contains_await(raw_code),
                detection_reason="python -c command (raw fallback after quote extraction failed)",
            )

        # 2. 检测 await 关键字（异步 Python 代码，非 python -c）
        if self._contains_await(command):
            return CodeDetectionResult(
                code_type=CodeType.PYTHON,
                extracted_code=command,
                is_async=True,
                detection_reason="contains await keyword",
            )

        # 3. 检测 Python 语法特征
        python_pattern = self._detect_python_pattern(command)
        if python_pattern:
            return CodeDetectionResult(
                code_type=CodeType.PYTHON,
                extracted_code=command,
                is_async=False,
                detection_reason=f"python syntax: {python_pattern}",
            )

        # 4. 默认作为 Bash 命令
        return CodeDetectionResult(
            code_type=CodeType.BASH, extracted_code=command, is_async=False, detection_reason="default to bash"
        )

    def _contains_await(self, command: str) -> bool:
        """检测命令中是否包含 await 关键字"""
        return bool(re.search(r"\bawait\b", command))

    def _is_python_command(self, command: str) -> bool:
        """检测是否是 python -c 命令"""
        return bool(re.search(r"python3?\s+-c", command))

    def _extract_python_code_from_command(self, command: str) -> str | None:
        """从 python -c 命令中提取代码（委托给统一提取器）。"""
        from myrm_agent_harness.agent.skills.mcp.python_extractor import (
            extract_python_from_bash,
        )

        return extract_python_from_bash(command)

    def _raw_extract_python_c(self, command: str) -> str:
        """Quote-aware 提取失败时的兜底:粗暴截取 ``-c`` 之后的全部内容。

        不做 quote-aware 解析（已由 ``python_extractor`` 失败），仅剥掉外层
        匹配的单/双引号。返回内容保证非空（最不济也是原命令本身），
        交由下游 ``ast.parse`` 做语法判定并触发 python -c hint。
        """
        match = self._RAW_PYTHON_C_RE.search(command)
        if not match:
            return command

        rest = match.group(1).strip()
        if len(rest) >= 2 and rest[0] in ("'", '"') and rest[-1] == rest[0]:
            return rest[1:-1]
        return rest

    def _detect_python_pattern(self, command: str) -> str | None:
        """检测 Python 语法特征

        只有当代码行数超过阈值时才进行检测，避免误判简单的 Bash 命令。

        Args:
            command: 要检测的代码

        Returns:
            匹配的模式名称，如果没有匹配返回 None
        """
        # 计算有效行数（排除空行和注释）
        lines = [
            line.strip() for line in command.strip().split("\n") if line.strip() and not line.strip().startswith("#")
        ]

        # 只有多行代码才进行语法特征检测
        if len(lines) <= self.MIN_LINES_FOR_MULTILINE_DETECTION:
            return None

        # 检测 Python 语法特征
        for pattern, name in self.PYTHON_PATTERNS:
            if re.search(pattern, command, re.MULTILINE):
                return name

        return None

    def is_python(self, command: str) -> bool:
        """快速判断是否是 Python 代码

        Args:
            command: 要检测的命令/代码

        Returns:
            True 如果是 Python 代码
        """
        return self.detect(command).code_type == CodeType.PYTHON

    def is_bash(self, command: str) -> bool:
        """快速判断是否是 Bash 命令

        Args:
            command: 要检测的命令/代码

        Returns:
            True 如果是 Bash 命令
        """
        return self.detect(command).code_type == CodeType.BASH


# 全局单例
code_detector = CodeTypeDetector()
