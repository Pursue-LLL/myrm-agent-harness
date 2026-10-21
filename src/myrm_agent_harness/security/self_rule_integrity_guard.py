"""核心自规约与凭据防篡改强审批安全护栏模块。

对标 Hermes Agent 最佳安全实践，针对 AGENTS.md、skills/、.env 与数据库等
核心系统规约的写操作实施物理审批门禁，并防御 Windows NT 命名空间穿透与
大小写不敏感文件系统路径逃逸，彻底终结 Prompt Injection 自越狱隐患。

[INPUT]
- __future__
- dataclasses
- os
- pathlib
- typing

[OUTPUT]
- FileSafetyVerdict
- SelfRuleIntegrityGuard

[POS]
核心自规约与凭据防篡改强审批安全护栏模块。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import List, Optional, Set

# 敏感环境变量与凭证文件名基准（全小写）
_PROTECTED_BASENAMES: Set[str] = {
    "agents.md",
    "agents2.md",
    "agents.json",
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    ".env.staging",
    ".envrc",
    "memory.db",
    "state.db",
    "myrm.db",
}

# 敏感目录名特征（全小写）
_PROTECTED_DIR_PARTS: Set[str] = {
    "skills",
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
}


@dataclass(frozen=True)
class FileSafetyVerdict:
    """文件写安全审计判决结果。"""

    is_denied: bool
    requires_approval: bool
    verdict: str
    reason: str


class SelfRuleIntegrityGuard:
    """系统自规约完整性守护器。"""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        custom_protected_basenames: Optional[Set[str]] = None,
    ) -> None:
        self._workspace_root = workspace_root.resolve() if workspace_root else None
        self._protected_basenames = (
            custom_protected_basenames or set(_PROTECTED_BASENAMES)
        )

    @staticmethod
    def is_nt_namespace_path(raw_path: str) -> bool:
        """检查原始字符串是否包含 Windows NT/设备命名空间前缀。

        必须在解析任何 Path 之前进行纯字符串预检，防止 NTLM 凭证外泄与前缀绕过。
        """
        s = raw_path.replace("/", "\\")
        if s.startswith("\\??\\") or s.startswith("\\\\.\\"):
            return True
        if s.startswith("\\\\?\\"):
            rest = s[4:].upper()
            if rest.startswith("UNC\\") or rest.startswith("GLOBALROOT\\"):
                return True
        return False

    def inspect_write_target(self, target_path: str) -> FileSafetyVerdict:
        """对即将发生写入的文件路径实施安全穿透审计。

        统一大小写规范化比对，支持 macOS APFS 与 Windows NTFS 安全防御。
        """
        # 1. Windows NT 命名空间预检拦截
        if self.is_nt_namespace_path(target_path):
            return FileSafetyVerdict(
                is_denied=True,
                requires_approval=False,
                verdict="HARD_DENY",
                reason=(
                    f"Write denied: '{target_path}' uses Windows NT/device namespace. "
                    "Bypasses path normalization and triggers credential leakage."
                ),
            )

        # 2. 符号链接完全穿透与真实物理路径规范化
        try:
            expanded = os.path.expanduser(str(target_path))
            real_path_str = os.path.realpath(expanded)
            resolved_path = Path(real_path_str)
        except Exception as exc:
            return FileSafetyVerdict(
                is_denied=True,
                requires_approval=False,
                verdict="PATH_RESOLUTION_FAILED",
                reason=f"Failed to resolve path '{target_path}': {exc}",
            )

        # 3. 大小写不敏感规范化基名比对
        basename_lower = resolved_path.name.lower()
        if basename_lower in self._protected_basenames:
            return FileSafetyVerdict(
                is_denied=False,
                requires_approval=True,
                verdict="REQUIRES_APPROVAL",
                reason=(
                    f"Modification of protected core rule/credential '{resolved_path.name}' "
                    "requires physical human approval to prevent prompt-injection jailbreak."
                ),
            )

        # 4. 路径各级目录敏感组件特征比对
        path_parts_lower = [part.lower() for part in resolved_path.parts]
        for protected_dir in _PROTECTED_DIR_PARTS:
            if protected_dir in path_parts_lower:
                return FileSafetyVerdict(
                    is_denied=False,
                    requires_approval=True,
                    verdict="REQUIRES_APPROVAL",
                    reason=(
                        f"Target path lies under protected directory '{protected_dir}'; "
                        "requires physical human approval to prevent unauthorized skill/credential tampering."
                    ),
                )

        # 5. 校验通过，安全放行
        return FileSafetyVerdict(
            is_denied=False,
            requires_approval=False,
            verdict="ALLOW",
            reason="Path verified safe for automated write operations.",
        )
