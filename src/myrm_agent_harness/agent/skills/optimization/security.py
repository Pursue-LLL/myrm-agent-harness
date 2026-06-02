"""Skill Security Validator

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .config::SecurityConfig (POS: 安全验证配置)
- .types::SecurityValidationResult, SecurityError (POS: 安全验证结果类型)
- backends.skills._utils::parse_skill_frontmatter (POS: 解析skill frontmatter)

[OUTPUT]
- SkillSecurityValidator: Skill安全验证器

[POS]
Multi-layer skill security validator. Prevents malicious code in LLM-generated skills.

"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import SecurityConfig
    from .types import SecurityValidationResult

logger = logging.getLogger(__name__)


class SkillSecurityValidator:
    """Skill安全验证器

    多层安全防护：
    1. 静态扫描：检测危险模式（rm -rf、eval()等）
    2. 语法验证：确保YAML frontmatter和Markdown格式正确
    3. 沙箱验证：可选的隔离环境执行测试
    """

    def __init__(self, config: SecurityConfig):
        """初始化安全验证器

        Args:
            config: 安全配置
        """
        self.config = config
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """预编译正则表达式模式（性能优化）"""
        self._compiled_patterns = [
            (pattern, re.compile(pattern, re.IGNORECASE | re.MULTILINE)) for pattern in self.config.dangerous_patterns
        ]

    def validate_skill(self, skill_content: str) -> SecurityValidationResult:
        """验证skill内容安全性

        Args:
            skill_content: skill内容（SKILL.md完整内容）

        Returns:
            SecurityValidationResult: 验证结果

        Raises:
            SecurityError: 验证失败且阻断
        """
        from .types import SecurityValidationResult

        issues: list[str] = []

        # 1. 静态安全扫描
        scan_issues = self._static_scan(skill_content)
        issues.extend(scan_issues)

        # 2. YAML frontmatter验证
        frontmatter_issues = self._validate_frontmatter(skill_content)
        issues.extend(frontmatter_issues)

        # 3. Markdown语法验证
        markdown_issues = self._validate_markdown(skill_content)
        issues.extend(markdown_issues)

        # 4. 可选：沙箱验证
        if self.config.enable_sandbox_validation and not issues:
            sandbox_issues = self._sandbox_validate(skill_content)
            issues.extend(sandbox_issues)

        # 汇总结果
        passed = len(issues) == 0

        if not passed:
            logger.warning(f"Security validation failed: {len(issues)} issues found")
            for issue in issues:
                logger.warning(f" - {issue}")

        return SecurityValidationResult(passed=passed, issues=issues)

    def _static_scan(self, content: str) -> list[str]:
        """静态安全扫描

        检测危险模式（rm -rf、eval()、DROP TABLE等）
        """
        issues: list[str] = []

        for pattern_str, compiled_pattern in self._compiled_patterns:
            matches = compiled_pattern.findall(content)
            if matches:
                issues.append(f"Dangerous pattern detected: {pattern_str} (matches: {len(matches)})")

        return issues

    def _validate_frontmatter(self, content: str) -> list[str]:
        """验证YAML frontmatter

        确保frontmatter格式正确，包含必需字段
        """
        issues: list[str] = []

        try:
            # 使用现有的frontmatter解析器
            from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter

            metadata = parse_skill_frontmatter(content, skill_dir_name="test-skill")

            # 检查必需字段
            if not getattr(metadata, "name", None):
                issues.append("Missing required field: name")

            if not getattr(metadata, "description", None):
                issues.append("Missing required field: description")

        except Exception as e:
            issues.append(f"Invalid YAML frontmatter: {e!s}")

        return issues

    def _validate_markdown(self, content: str) -> list[str]:
        """验证Markdown语法

        基本的格式检查（不需要完整的Markdown解析器）
        """
        issues: list[str] = []

        # 检查是否有frontmatter分隔符
        if not content.startswith("---"):
            issues.append("Missing YAML frontmatter delimiter (---)")

        # 检查frontmatter是否闭合
        frontmatter_parts = content.split("---")
        if len(frontmatter_parts) < 3:
            issues.append("Unclosed YAML frontmatter")

        return issues

    def _sandbox_validate(self, content: str) -> list[str]:
        """沙箱执行验证

        在隔离环境中执行skill，检测运行时行为。
        注意：此功能耗时且复杂，仅在高安全要求时启用。

        TODO: 实现完整的沙箱执行验证
        - 创建隔离的Python环境
        - 监控文件系统访问
        - 监控网络请求
        - 超时保护
        """
        issues: list[str] = []

        # 暂未实现完整沙箱验证
        # 这需要：
        # 1. 创建Docker容器或虚拟环境
        # 2. 安装必要的依赖
        # 3. 执行skill并监控行为
        # 4. 检测异常操作（文件删除、网络攻击等）

        logger.warning("Sandbox validation is enabled but not fully implemented yet")

        return issues
