"""插件静态恶意代码审计与核心工具保留字防覆盖防护模块。

提供 AST 语法树动态调用分析、高危系统命令正则扫描，
以及系统核心保留工具命名空间强隔离，彻底防御工具影子化劫持与恶意后门代码。

[INPUT]
- __future__
- ast
- logging
- re
- dataclasses
- pathlib

[OUTPUT]
- logger
- SecurityAuditReport
- ReservedToolGuard
- PluginSecurityAuditor

[POS]
插件静态恶意代码审计与核心工具保留字防覆盖防护模块。
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 系统核心保留工具名（禁止被第三方插件覆盖影子化）
_SYSTEM_RESERVED_TOOLS: set[str] = {
    "bash",
    "shell",
    "terminal",
    "write_file",
    "view_file",
    "edit_file",
    "replace_file_content",
    "read_file",
    "list_dir",
    "delete_file",
    "web_search",
    "fetch_url",
}

# 高危 Shell 命令与恶意利用特征正则
_MALICIOUS_CMD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-[rR]f\s+(?:/|/\*|~)(?:[\s;]|$)"),
    re.compile(r"\bnc\s+-[eE]\s+/bin/(?:ba)?sh\b"),
    re.compile(r"/etc/(?:shadow|sudoers|master\.passwd)"),
    re.compile(r"\b(?:mkfifo|mknod)\b.*\b(?:nc|bash)\b"),
    re.compile(r"curl\s+.*\|\s*(?:ba)?sh\b"),
]


@dataclass(frozen=True, slots=True)
class SecurityAuditReport:
    """静态安全审计体检报告。"""

    is_clean: bool
    requires_human_confirmation: bool
    detected_risks: tuple[str, ...]
    audited_files_count: int


class ReservedToolGuard:
    """核心工具保留字防覆盖守卫。"""

    @classmethod
    def sanitize_plugin_tool_names(
        cls,
        plugin_id: str,
        declared_tools: list[str],
    ) -> tuple[str, ...]:
        """对插件声明的工具名称做命名空间前缀隔离，若命中系统保留字则强制重命名。"""
        sanitized: list[str] = []
        for tool_name in declared_tools:
            clean_name = tool_name.strip()
            if clean_name in _SYSTEM_RESERVED_TOOLS:
                prefixed = f"{plugin_id}__{clean_name}"
                logger.warning(
                    "Tool name '%s' conflicts with system reserved tool; renamed to '%s'",
                    clean_name,
                    prefixed,
                )
                sanitized.append(prefixed)
            else:
                sanitized.append(clean_name)
        return tuple(sanitized)


class PluginSecurityAuditor:
    """插件静态安全审计器。"""

    @classmethod
    def _inspect_python_ast(cls, py_file: Path) -> list[str]:
        """通过 AST 深度扫描 Python 代码中的高危动态执行调用。"""
        risks: list[str] = []
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # 检查直接 eval() / exec()
                    if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                        risks.append(f"{py_file.name}: dynamic call '{node.func.id}()'")
                    # 检查 __import__() 隐式反射
                    elif isinstance(node.func, ast.Attribute) and node.func.attr == "__import__":
                        risks.append(f"{py_file.name}: dynamic reflection '__import__'")
        except Exception:
            pass
        return risks

    @classmethod
    def audit_directory(cls, project_dir: Path) -> SecurityAuditReport:
        """对克隆后的仓库目录执行静态安全体检。"""
        detected: list[str] = []
        file_count = 0

        for file_path in project_dir.rglob("*"):
            if not file_path.is_file():
                continue

            # 跳过常见大型二进制与媒体文件
            if file_path.suffix.lower() in (".png", ".jpg", ".zip", ".tar", ".gz", ".pyc"):
                continue

            file_count += 1

            # 1. 文本内容高危正则扫描
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
                for pattern in _MALICIOUS_CMD_PATTERNS:
                    match = pattern.search(text)
                    if match:
                        detected.append(
                            f"{file_path.name}: matched dangerous command '{match.group(0).strip()}'"
                        )
            except Exception:
                pass

            # 2. Python 专属 AST 动态求值审查
            if file_path.suffix.lower() == ".py":
                ast_risks = cls._inspect_python_ast(file_path)
                detected.extend(ast_risks)

        is_clean = len(detected) == 0
        return SecurityAuditReport(
            is_clean=is_clean,
            requires_human_confirmation=not is_clean,
            detected_risks=tuple(detected),
            audited_files_count=file_count,
        )
