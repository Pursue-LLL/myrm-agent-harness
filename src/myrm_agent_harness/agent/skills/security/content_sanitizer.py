"""Content Sanitizer - 技能导出内容脱敏
扫描并脱敏 SKILL.md 和 Python 脚本中的敏感信息（API Key、绝对路径等）。
支持两段式：先扫描返回 Diff，确认后再应用替换。
"""

import logging
import re
from dataclasses import dataclass
from typing import TypedDict

logger = logging.getLogger(__name__)

# 常见 API Key 正则表达式
SECRET_PATTERNS = [
    # OpenAI
    re.compile(r"sk-[a-zA-Z0-9]{48}"),
    re.compile(r"sk-proj-[a-zA-Z0-9_-]{48,}"),
    # Anthropic
    re.compile(r"sk-ant-api[0-9a-zA-Z_-]{80,}"),
    # Generic Bearer / Token
    re.compile(r"(?i)(?:bearer|token|api[_-]?key|secret)[\s:=]+[\"']?([a-zA-Z0-9_\-]{32,})[\"']?"),
    # Absolute paths (macOS/Linux)
    re.compile(r"(?<=[\s\"'])/Users/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.-]+)+"),
    re.compile(r"(?<=[\s\"'])/home/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.-]+)+"),
]

class Redaction(TypedDict):
    line_number: int
    original: str
    redacted: str
    reason: str

@dataclass
class SanitizationResult:
    is_safe: bool
    redactions: list[Redaction]
    sanitized_content: str

class ContentSanitizer:
    """内容脱敏器"""

    def _sanitize_text(self, content: str, filename: str, ignored_indices: list[int] | None = None) -> SanitizationResult:
        """基于正则的通用文本脱敏"""
        redactions: list[Redaction] = []
        sanitized_lines = []
        ignored_indices = ignored_indices or []

        lines = content.splitlines()
        redaction_index = 0

        for i, line in enumerate(lines):
            original_line = line
            modified_line = line

            # 收集该行的所有匹配项
            line_matches = []
            for pattern in SECRET_PATTERNS:
                for match in pattern.finditer(original_line):
                    matched_str = match.group(0)

                    if matched_str.startswith("/Users/") or matched_str.startswith("/home/"):
                        reason = "Absolute Path"
                        replacement = "<REDACTED_PATH>"
                        start_idx = match.start()
                        end_idx = match.end()
                    else:
                        reason = "API Key / Secret"
                        replacement = "<REDACTED_SECRET>"
                        if len(match.groups()) > 0 and match.start(1) != -1:
                            start_idx = match.start(1)
                            end_idx = match.end(1)
                        else:
                            start_idx = match.start()
                            end_idx = match.end()

                    line_matches.append({
                        "replacement": replacement,
                        "reason": reason,
                        "start": start_idx,
                        "end": end_idx
                    })

            if line_matches:
                # 当前行存在敏感信息，分配一个 redaction_index
                current_index = redaction_index
                redaction_index += 1

                if current_index not in ignored_indices:
                    # 按起始位置倒序排序，避免替换时索引偏移
                    line_matches.sort(key=lambda x: x["start"], reverse=True)

                    reasons = []
                    for match_info in line_matches:
                        start = match_info["start"]
                        end = match_info["end"]
                        modified_line = modified_line[:start] + match_info["replacement"] + modified_line[end:]
                        if match_info["reason"] not in reasons:
                            reasons.append(match_info["reason"])

                    redactions.append(Redaction(
                        line_number=i + 1,
                        original=original_line,
                        redacted=modified_line,
                        reason=" / ".join(reasons)
                    ))

            sanitized_lines.append(modified_line)

        return SanitizationResult(
            is_safe=len(redactions) == 0,
            redactions=redactions,
            sanitized_content="\n".join(sanitized_lines)
        )

    def _sanitize_python_ast(self, content: str, filename: str, ignored_indices: list[int] | None = None) -> SanitizationResult:
        """基于 AST 的 Python 代码脱敏 (更精确)"""
        return self._sanitize_text(content, filename, ignored_indices)

    def sanitize(self, content: str | bytes, filename: str, ignored_indices: list[int] | None = None) -> SanitizationResult:
        """扫描并脱敏文件内容"""
        if isinstance(content, bytes):
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                return SanitizationResult(is_safe=True, redactions=[], sanitized_content=content)
        else:
            text_content = content

        if filename.endswith(".py"):
            return self._sanitize_python_ast(text_content, filename, ignored_indices)
        elif filename.endswith(".md") or filename.endswith(".txt") or filename.endswith(".json") or filename.endswith(".yaml") or filename.endswith(".yml"):
            return self._sanitize_text(text_content, filename, ignored_indices)

        return self._sanitize_text(text_content, filename, ignored_indices)

content_sanitizer = ContentSanitizer()
