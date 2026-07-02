"""工具结果验证器（Context Poisoning 检测）

此模块提供基于规则的验证，用于检测工具结果中的潜在问题：
1. 显式错误标记（Error:、Failed:、Exception:）
2. HTTP/网络/系统错误
3. 搜索结果异常短
4. 可疑的 Prompt Injection 模式

使用纯规则检测，无需额外的模型调用。

[INPUT]
- (none)

[OUTPUT]
- ValidationResult: Validation result.
- validate_tool_result: Args:
- should_apply_validation: Args:

[POS]
Provides ValidationResult, validate_tool_result, should_apply_validation.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """工具结果验证结果

    用于 Context Poisoning 检测。

    Attributes:
        is_valid: 结果是否有效
        reason: 无效时的说明
        severity: 严重程度（info/warning/error）
    """

    is_valid: bool
    reason: str = ""
    severity: str = "info"  # info, warning, error


# Error prefixes (error level)
ERROR_PREFIXES: tuple[str, ...] = (
    "Error:",
    "error:",
    "Failed:",
    "failed:",
    "Exception:",
    "Traceback (most recent call last):",
)

# Error patterns (warning level)
ERROR_PATTERNS: tuple[str, ...] = (
    # HTTP errors
    "404 Not Found",
    "403 Forbidden",
    "401 Unauthorized",
    "500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
    # Network errors
    "Connection refused",
    "Connection timed out",
    "ETIMEDOUT",
    "ECONNREFUSED",
    "Network is unreachable",
    # System errors
    "Permission denied",
    "No such file or directory",
    "Operation not permitted",
)

# Search-related tools
SEARCH_TOOLS: frozenset[str] = frozenset({"web_search_tool"})

# Prompt Injection patterns
INJECTION_PATTERNS: tuple[str, ...] = (
    "忽略之前的指令",
    "ignore previous instructions",
    "disregard all prior",
    "你现在是",
    "you are now",
    "new role:",
)


def validate_tool_result(content: str, tool_name: str) -> ValidationResult:
    """验证工具结果（Context Poisoning 检测）

    检查项：
    1. 显式错误标记（高严重程度）
    2. 常见错误模式（中等严重程度）
    3. 搜索结果过短（低严重程度）
    4. Prompt Injection 尝试（高严重程度）

    Args:
        content: 工具结果内容
        tool_name: 工具名称

    Returns:
        ValidationResult，包含 is_valid、reason 和 severity

    Example:
        >>> result = validate_tool_result("Error: Connection failed", "web_search")
        >>> result.is_valid
        False
        >>> result.severity
        'error'
    """
    if not content:
        return ValidationResult(is_valid=True)

    content_lower = content.lower()

    # 1. Check explicit error markers (error level)
    for prefix in ERROR_PREFIXES:
        if content.startswith(prefix):
            logger.debug(f"Detected error prefix in {tool_name}: {prefix}")
            return ValidationResult(
                is_valid=False, reason=f"Content starts with error marker: {prefix}", severity="error"
            )

    # 2. Check common error patterns (warning level)
    for pattern in ERROR_PATTERNS:
        if pattern.lower() in content_lower:
            logger.debug(f"Detected error pattern in {tool_name}: {pattern}")
            return ValidationResult(
                is_valid=False, reason=f"Content contains error pattern: {pattern}", severity="warning"
            )

    # 3. Check short search results (warning level)
    # Search results should be substantial
    if tool_name in SEARCH_TOOLS and len(content) < 50:
        logger.debug(f"Detected unusually short search result in {tool_name}")
        return ValidationResult(
            is_valid=False,
            reason="Search result is unusually short (< 50 chars), may indicate an error",
            severity="warning",
        )

    # 4. Check Prompt Injection patterns (error level)
    for pattern in INJECTION_PATTERNS:
        if pattern.lower() in content_lower:
            logger.warning(f"Detected potential prompt injection in {tool_name}: {pattern}")
            return ValidationResult(
                is_valid=False,
                reason=f"Content contains suspicious prompt injection pattern: {pattern}",
                severity="error",
            )

    return ValidationResult(is_valid=True)


def should_apply_validation(tool_name: str) -> bool:
    """检查是否应对此工具应用验证

    某些工具（如文件系统工具）可能不需要验证。

    Args:
        tool_name: 工具名称

    Returns:
        如果应应用验证则返回 True
    """
    # Skip validation for certain internal tools
    skip_tools = {"file_write_tool", "file_edit_tool"}
    return tool_name not in skip_tools
