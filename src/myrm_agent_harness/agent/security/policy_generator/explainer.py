"""Deterministic human-readable explanation generator for security policies.

Converts a SecurityConfig dict into a natural language summary that users
can read to understand what the policy does before confirming.

[INPUT]
- Generated policy config dict

[OUTPUT]
- explain_policy(): human-readable explanation string (supports zh/en)

[POS]
Deterministic explainer — no LLM calls. Pure string formatting.
"""

from __future__ import annotations

_PERMISSION_LABELS: dict[str, tuple[str, str]] = {
    "shell_exec": ("Shell 命令执行", "Shell command execution"),
    "file_read": ("文件读取", "File read"),
    "file_write": ("文件写入", "File write"),
    "file_delete": ("文件删除", "File delete"),
    "code_interpreter": ("代码执行", "Code execution"),
    "browser_navigate": ("网页浏览", "Web navigation"),
    "browser_fill": ("表单填写", "Form filling"),
    "browser_upload": ("文件上传", "File upload"),
    "browser_download": ("文件下载", "File download"),
    "browser_session": ("浏览器会话", "Browser session"),
    "mcp_invoke": ("MCP 工具调用", "MCP tool invocation"),
    "web_search_tool": ("网页搜索", "Web search"),
    "net_fetch": ("网络请求", "Network fetch"),
    "delegate_agent": ("子智能体委派", "Sub-agent delegation"),
}

_ACTION_LABELS: dict[str, tuple[str, str]] = {
    "allow": ("允许", "Allow"),
    "ask": ("需审批", "Require approval"),
    "deny": ("禁止", "Deny"),
}

_PII_ACTION_LABELS: dict[str, tuple[str, str]] = {
    "warn": ("仅警告", "Warn only"),
    "redact": ("不可逆脱敏", "Irreversible redact"),
    "pseudonymize": ("可逆脱敏", "Reversible pseudonymize"),
    "block": ("拒绝", "Block"),
}


def explain_policy(config: dict[str, object], locale: str = "zh") -> str:
    """Generate a human-readable explanation of a security policy config.

    Args:
        config: SecurityConfig-compatible dict.
        locale: 'zh' for Chinese, 'en' for English.

    Returns:
        Multi-line human-readable summary.
    """
    idx = 0 if locale == "zh" else 1
    lines: list[str] = []

    _explain_permissions(config, lines, idx)
    _explain_path_policy(config, lines, idx)
    _explain_privacy(config, lines, idx)
    _explain_network(config, lines, idx)
    _explain_misc(config, lines, idx)

    if not lines:
        return "无变更" if locale == "zh" else "No changes"

    return "\n".join(lines)


def _explain_permissions(
    config: dict[str, object], lines: list[str], idx: int
) -> None:
    """Explain permission rules."""
    permissions = config.get("permissions")
    if not isinstance(permissions, dict):
        return

    header = "权限规则：" if idx == 0 else "Permission rules:"
    lines.append(header)

    for perm, value in permissions.items():
        perm_label = _PERMISSION_LABELS.get(perm, (perm, perm))[idx]

        if isinstance(value, str):
            action_label = _ACTION_LABELS.get(value, (value, value))[idx]
            lines.append(f"  • {perm_label}: {action_label}")
        elif isinstance(value, dict):
            for pattern, action in value.items():
                action_label = _ACTION_LABELS.get(str(action), (str(action), str(action)))[idx]
                lines.append(f"  • {perm_label} [{pattern}]: {action_label}")


def _explain_path_policy(
    config: dict[str, object], lines: list[str], idx: int
) -> None:
    """Explain path policy."""
    path_policy = config.get("pathPolicy")
    if not isinstance(path_policy, dict):
        return

    allowed = path_policy.get("allowedRoots")
    if isinstance(allowed, list) and allowed:
        header = "路径访问：" if idx == 0 else "Path access:"
        lines.append(header)
        for root in allowed:
            lines.append(f"  • {root}")

    forbidden = path_policy.get("forbiddenPaths")
    if isinstance(forbidden, list) and forbidden:
        header = "禁止路径：" if idx == 0 else "Forbidden paths:"
        lines.append(header)
        for path in forbidden:
            lines.append(f"  • {path}")


def _explain_privacy(
    config: dict[str, object], lines: list[str], idx: int
) -> None:
    """Explain privacy policy."""
    privacy = config.get("privacyPolicy")
    if not isinstance(privacy, dict):
        return

    header = "隐私保护：" if idx == 0 else "Privacy protection:"
    lines.append(header)

    if privacy.get("enabled"):
        s2 = privacy.get("s2Action", "warn")
        s3 = privacy.get("s3Action", "redact")
        s2_label = _PII_ACTION_LABELS.get(str(s2), (str(s2), str(s2)))[idx]
        s3_label = _PII_ACTION_LABELS.get(str(s3), (str(s3), str(s3)))[idx]

        s2_desc = ("敏感信息（手机号/邮箱）", "Sensitive (phone/email)")[idx]
        s3_desc = ("机密信息（身份证/银行卡）", "Confidential (ID/bank card)")[idx]
        lines.append(f"  • {s2_desc}: {s2_label}")
        lines.append(f"  • {s3_desc}: {s3_label}")

        if privacy.get("deepScan"):
            deep_label = ("启用深度扫描", "Deep scan enabled")[idx]
            lines.append(f"  • {deep_label}")


def _explain_network(
    config: dict[str, object], lines: list[str], idx: int
) -> None:
    """Explain network allowlist."""
    allowlist = config.get("networkAllowlist")
    if isinstance(allowlist, list) and allowlist:
        header = ("信任域名：", "Trusted domains:")[idx]
        lines.append(header)
        for domain in allowlist:
            lines.append(f"  • {domain}")

    hitl = config.get("domainHitlEnabled")
    if hitl is not None:
        if hitl:
            label = ("未知域名需审批", "Unknown domains require approval")[idx]
        else:
            label = ("未知域名无需审批", "Unknown domains auto-allowed")[idx]
        lines.append(f"  • {label}")


def _explain_misc(
    config: dict[str, object], lines: list[str], idx: int
) -> None:
    """Explain miscellaneous settings."""
    timeout = config.get("approvalTimeoutSeconds")
    if isinstance(timeout, (int, float)):
        label = (f"审批超时: {int(timeout)}秒", f"Approval timeout: {int(timeout)}s")[idx]
        lines.append(label)

    behavior = config.get("approvalTimeoutBehavior")
    if behavior:
        b_label = ("超时后拒绝", "Deny on timeout") if behavior == "deny" else ("超时后允许", "Allow on timeout")
        lines.append(f"  • {b_label[idx]}")
