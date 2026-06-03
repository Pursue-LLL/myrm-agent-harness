"""Content Sanitizer - 技能导出内容脱敏
扫描并脱敏 SKILL.md 和 Python 脚本中的敏感信息（API Key、绝对路径等）。
支持两段式：先扫描返回 Diff，确认后再应用替换。
"""

import ast
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

    def _sanitize_text(self, content: str, filename: str) -> SanitizationResult:
        """基于正则的通用文本脱敏"""
        redactions: list[Redaction] = []
        sanitized_lines = []
        
        lines = content.splitlines()
        for i, line in enumerate(lines):
            original_line = line
            modified_line = line
            
            for pattern in SECRET_PATTERNS:
                for match in pattern.finditer(modified_line):
                    matched_str = match.group(0)
                    
                    # Determine reason and replacement
                    if matched_str.startswith("/Users/") or matched_str.startswith("/home/"):
                        reason = "Absolute Path"
                        replacement = "<REDACTED_PATH>"
                    else:
                        reason = "API Key / Secret"
                        replacement = "<REDACTED_SECRET>"
                        
                        # If it's a generic match, we might have captured the prefix too, 
                        # so we only replace the actual secret part if we used a capture group
                        if len(match.groups()) > 0:
                            matched_str = match.group(1)
                    
                    modified_line = modified_line.replace(matched_str, replacement)
            
            if modified_line != original_line:
                redactions.append(Redaction(
                    line_number=i + 1,
                    original=original_line,
                    redacted=modified_line,
                    reason=reason
                ))
            
            sanitized_lines.append(modified_line)
            
        return SanitizationResult(
            is_safe=len(redactions) == 0,
            redactions=redactions,
            sanitized_content="\n".join(sanitized_lines)
        )

    def _sanitize_python_ast(self, content: str, filename: str) -> SanitizationResult:
        """基于 AST 的 Python 代码脱敏 (更精确)"""
        # 为了简单起见，目前 Python 也复用正则脱敏。
        # 完整的 AST 脱敏可以遍历 ast.Constant 寻找敏感字符串，
        # 但正则已经能覆盖大部分硬编码场景，且实现更轻量。
        return self._sanitize_text(content, filename)

    def sanitize(self, content: str | bytes, filename: str) -> SanitizationResult:
        """扫描并脱敏文件内容"""
        if isinstance(content, bytes):
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                # 二进制文件不处理
                return SanitizationResult(is_safe=True, redactions=[], sanitized_content=content)
        else:
            text_content = content

        if filename.endswith(".py"):
            return self._sanitize_python_ast(text_content, filename)
        elif filename.endswith(".md") or filename.endswith(".txt") or filename.endswith(".json") or filename.endswith(".yaml") or filename.endswith(".yml"):
            return self._sanitize_text(text_content, filename)
        
        # 其他文本文件也尝试正则
        return self._sanitize_text(text_content, filename)

content_sanitizer = ContentSanitizer()
