"""Path security — single source of truth for dangerous paths and sensitive files.

All path-based security knowledge lives here. Both the permission engine
(Layer 2.5 PathPolicy) and the file-operation validators reference this
module, ensuring a single set of definitions and consistent checks.

[INPUT]
- (none — pure data + logic module)

[OUTPUT]
- DANGEROUS_PATHS: frozenset[str] — normalised dangerous root paths
- SENSITIVE_FILE_PATTERNS: tuple[str, ...] — glob patterns for sensitive files
- is_dangerous_path(path) -> bool — unified check function
- is_sensitive_file(path) -> bool — sensitive file check function
- is_within_boundary(target, boundary) -> bool — boundary check immune to symlink escape
- safe_join_path(base_dir, user_input) -> Path — secure path resolution against traversal

[INPUT]
- (none)

[OUTPUT]
- is_dangerous_path: Check if *path* falls under any dangerous root.
- is_sensitive_file: Check if *path* matches any sensitive file pattern.

[POS]
Path security — single source of truth for dangerous paths and sensitive files.
"""

from __future__ import annotations

import os
import platform
from fnmatch import fnmatch
from pathlib import Path

# ---------------------------------------------------------------------------
# Dangerous path roots (normalised at import time)
# ---------------------------------------------------------------------------

_UNIX_SYSTEM_ROOTS: tuple[str, ...] = ("/etc", "/sys", "/proc", "/dev", "/root", "/boot", "/var/log")

_USER_SENSITIVE_DIRS: tuple[str, ...] = (
    "~/.ssh",
    "~/.gnupg",
    "~/.gpg",
    "~/.aws",
    "~/.config/gcloud",
    "~/.azure",
    "~/.config",
    "~/.docker",
    "~/.kube",
    "~/.bash_history",
    "~/.zsh_history",
)

_WIN_SYSTEM_ROOTS: tuple[str, ...] = (
    "C:\\Windows\\System32",
    "C:\\Windows\\SysWOW64",
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\ProgramData",
)


def _build_dangerous_paths() -> frozenset[str]:
    """Build normalised set of dangerous path roots at import time."""
    roots: set[str] = set()
    for p in _UNIX_SYSTEM_ROOTS:
        roots.add(os.path.realpath(p))
    for p in _USER_SENSITIVE_DIRS:
        roots.add(os.path.realpath(os.path.expanduser(p)))
    if platform.system() == "Windows":
        for p in _WIN_SYSTEM_ROOTS:
            roots.add(os.path.realpath(p))
    return frozenset(roots)


DANGEROUS_PATHS: frozenset[str] = _build_dangerous_paths()
"""Normalised absolute paths that are considered dangerous.

Used by both ``types.PathPolicy`` (Layer 2.5) and
``path_validator.PathValidator`` (file-operation layer).
"""

# ---------------------------------------------------------------------------
# Sensitive file patterns
# ---------------------------------------------------------------------------

SENSITIVE_FILE_PATTERNS: tuple[str, ...] = (
    # Credentials and keys
    "**/id_rsa",
    "**/id_dsa",
    "**/id_ecdsa",
    "**/id_ed25519",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    # Environment files
    "**/.env*",
    "**/credentials.json",
    "**/secrets.json",
    "**/config.json",
    # AWS credentials
    "**/.aws/credentials",
    "**/.aws/config",
    # Git config (may contain tokens)
    "**/.git/config",
    # Database files
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    # Password files
    "**/password.txt",
    "**/passwd",
    "**/shadow",
)

# ---------------------------------------------------------------------------
# Path boundary and safe join checks
# ---------------------------------------------------------------------------


def is_within_boundary(target: str | Path, boundary: str | Path) -> bool:
    """严格检查目标路径是否处于边界目录内。

    基于真实物理路径（resolve）进行校验，防御符号链接逃逸，
    并使用现代的 is_relative_to() 替代脆弱的字符串前缀匹配。
    """
    try:
        t = Path(target).resolve()
        b = Path(boundary).resolve()
        return t.is_relative_to(b)
    except Exception:
        return False


def safe_join_path(base_dir: str | Path, user_input: str | Path) -> Path:
    """安全地拼接并解析路径，防御所有已知路径攻击，同时保持虚拟路径兼容性。

    防御向量：
    1. 空字节注入 (Null Byte Injection)
    2. 绝对路径替换攻击
    3. 目录遍历 (Directory Traversal, ../)
    4. 符号链接逃逸 (Symlink attacks)

    架构亮点：
    - 验证环节使用真实的物理路径（resolve()）确保无逃逸风险。
    - 最终返回规范化后的虚拟（未 resolve）绝对路径，
      确保 Docker 挂载卷、软链接工作区等外部系统依赖的路径前缀不变，杜绝兼容性 Bug。

    Args:
        base_dir: 基础安全边界目录
        user_input: 用户输入的相对路径

    Returns:
        拼接并规范化后的虚拟绝对路径 (Path)

    Raises:
        ValueError: 如果检测到任何路径攻击或解析失败
    """
    input_str = str(user_input)
    if "\0" in input_str:
        raise ValueError("Null byte injection detected in path")

    user_path = Path(user_input)
    if user_path.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {user_input}")

    # 获取虚拟绝对基路径（不展开符号链接）
    base_path_obj = Path(base_dir).absolute()

    # 获取虚拟绝对最终路径
    import os

    final_virtual_path = Path(os.path.normpath(base_path_obj / user_path))

    try:
        # 进行安全的物理边界校验
        resolved_final = final_virtual_path.resolve()
        resolved_base = base_path_obj.resolve()
    except Exception as e:
        raise ValueError(f"Path resolution failed: {e}") from e

    if not resolved_final.is_relative_to(resolved_base):
        raise ValueError(f"Path traversal detected: {user_input} resolves outside base directory")

    return final_virtual_path


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def is_dangerous_path(path: str) -> bool:
    """Check if *path* falls under any dangerous root.

    Uses normalised absolute-path prefix comparison — stricter than
    substring matching and immune to partial-name false positives.
    """
    normalised = os.path.realpath(os.path.expanduser(path))
    return any(normalised == dp or normalised.startswith(dp + os.sep) for dp in DANGEROUS_PATHS)


def is_sensitive_file(path: str) -> bool:
    """Check if *path* matches any sensitive file pattern."""
    path_obj = Path(path)
    abs_path = str(path_obj.absolute())
    file_name = path_obj.name

    for pattern in SENSITIVE_FILE_PATTERNS:
        if fnmatch(abs_path, pattern):
            return True
        file_pattern = pattern.replace("**/", "")
        if fnmatch(file_name, file_pattern):
            return True
    return False
