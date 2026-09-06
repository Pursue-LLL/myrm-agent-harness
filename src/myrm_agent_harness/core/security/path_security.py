"""Path security — single source of truth for dangerous paths and sensitive files.

All path-based security knowledge lives here. Both the permission engine
(Layer 2.5 PathPolicy) and the file-operation validators reference this
module, ensuring a single set of definitions and consistent checks.

[INPUT]
- (none — pure data + logic module)

[OUTPUT]
- DANGEROUS_PATHS: frozenset[str] — normalised dangerous root paths
- BLOCKED_DEVICE_NAMES: frozenset[str] — Windows reserved device names
- SENSITIVE_FILE_PATTERNS: tuple[str, ...] — glob patterns for sensitive files
- PROTECTED_INSTRUCTION_PATTERNS: tuple[str, ...] — glob patterns for protected instruction files
- MAX_PATH_LENGTH: int — maximum allowed path length (4096 bytes)
- is_content_not_path(value) -> bool — disambiguates multiline/oversized text from filesystem path
- coerce_filesystem_path(value) -> Path | None — runtime path coercion; rejects unittest.mock objects and text content
- is_dangerous_path(path) -> bool — unified check function
- is_blocked_device_path(path) -> bool — pre-IO device path blocklist check
- is_sensitive_file(path) -> bool — sensitive file check function
- is_protected_instruction_file(path) -> bool — protected instruction check function
- is_evidence_readonly_file(path) -> bool — read-only session evidence check function
- is_within_boundary(target, boundary) -> bool — boundary check immune to symlink escape
- safe_join_path(base_dir, user_input) -> Path — secure path resolution against traversal

[POS]
Path security — single source of truth for dangerous paths and sensitive files.
"""

from __future__ import annotations

import os
import platform
import stat
from fnmatch import fnmatch
from pathlib import Path

# ---------------------------------------------------------------------------
# Dangerous path roots (normalised at import time)
# ---------------------------------------------------------------------------

_UNIX_SYSTEM_ROOTS: tuple[str, ...] = (
    "/etc",
    "/sys",
    "/proc",
    "/dev",
    "/root",
    "/boot",
    "/var/log",
)

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

BLOCKED_DEVICE_NAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)
"""Windows reserved device names (matched case-insensitively with or without extensions)."""

_DEVICE_PREFIXES: tuple[str, ...] = (
    "\\\\.\\",
    "//./",
    "\\\\?\\",
    "//?/",
    "/dev/",
    "dev/",
    "/proc/",
    "proc/",
    "/sys/",
    "sys/",
)

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
# Protected instruction file patterns (anti-persona tampering & prompt injection persistence)
# ---------------------------------------------------------------------------

PROTECTED_INSTRUCTION_PATTERNS: tuple[str, ...] = (
    "**/AGENTS.md",
    "**/CLAUDE.md",
    "**/SOUL.md",
    "**/USER.md",
    "**/.user.md",
    "**/MEMORY.md",
    "**/.myrm.md",
    "**/myrm.md",
    "**/.hermes.md",
    "**/HERMES.md",
    "**/.cursorrules",
    "**/.clinerules",
    "**/.windsurfrules",
    "**/.cursor/rules/**",
    "**/.myrm/rules/**",
    "**/.claude/CLAUDE.md",
    "**/.github/copilot-instructions.md",
)

# ---------------------------------------------------------------------------
# Session Evidence and Read-only Input File Patterns
# ---------------------------------------------------------------------------

EVIDENCE_READONLY_PATTERNS: tuple[str, ...] = (
    "**/evidence/**",
    "**/evidence/*",
    "evidence/**",
    "evidence/*",
    "**/user_inputs/**",
    "**/user_inputs/*",
    "user_inputs/**",
    "user_inputs/*",
    "**/.evidence/**",
    "**/.evidence/*",
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
        ValueError: 如果检测到任何路径攻击、解析失败或传入文本内容而非路径
    """
    input_str = str(user_input)
    if "\0" in input_str:
        raise ValueError("Null byte injection detected in path")
    if is_content_not_path(input_str):
        raise ValueError(
            "Invalid path: content or multiline string cannot be parsed as a filesystem path"
        )

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
        raise ValueError(
            f"Path traversal detected: {user_input} resolves outside base directory"
        )

    return final_virtual_path


# ---------------------------------------------------------------------------
# Path coercion and content disambiguation (runtime type guard)
# ---------------------------------------------------------------------------

MAX_PATH_LENGTH: int = 4096


def is_content_not_path(value: object) -> bool:
    """Return True if *value* is clearly multiline/oversized text content rather than a path.

    Defends against bugs where memory plugins or URI guards misclassify code snippets,
    Markdown text, or multiline strings as filesystem paths, preventing OS Errno 36
    (File name too long) and false-positive security alerts.
    """
    if not isinstance(value, str):
        return False
    if len(value) > MAX_PATH_LENGTH:
        return True
    if "\n" in value or "\r" in value:
        return True
    if "```" in value:
        return True
    return False


def _is_unittest_mock(value: object) -> bool:
    """True when *value* is a unittest.mock object (implements os.PathLike via __fspath__)."""
    return getattr(type(value), "__module__", "") == "unittest.mock"


def coerce_filesystem_path(value: object) -> Path | None:
    """Coerce a runtime value to a filesystem path, or return None if invalid.

    Only ``str``, ``Path``, and non-mock ``os.PathLike`` are accepted. Rejects
    MagicMock, multiline text, oversized content, and other non-path objects.
    """
    if value is None:
        return None
    if _is_unittest_mock(value):
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or is_content_not_path(stripped):
            return None
        return Path(stripped)
    if isinstance(value, os.PathLike):
        return Path(value)
    return None


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def is_dangerous_path(path: str) -> bool:
    """Check if *path* falls under any dangerous root.

    Uses canonical boundary guard — stricter than
    substring matching and immune to partial-name false positives.
    """
    if not path or not path.strip() or is_content_not_path(path):
        return False
    try:
        normalised = os.path.realpath(os.path.expanduser(path))
        return any(is_within_boundary(normalised, dp) for dp in DANGEROUS_PATHS)
    except Exception:
        return False


def is_blocked_device_path(path: str) -> bool:
    """Check if *path* refers to a blocked character/block/special or Windows device.

    Performs pre-IO static inspection of path patterns (Windows device names,
    POSIX special filesystems) as well as filesystem stat mode checks when the
    path exists. Immune to trailing spaces, slashes, or alternate casings.
    """
    if not path or not path.strip() or is_content_not_path(path):
        return False

    cleaned = path.strip()
    norm_slash = cleaned.replace("\\", "/")

    # 1. Device namespace prefixes (\\.\, //./, \\?\, //?/)
    for prefix in ("\\\\.\\", "//./", "\\\\?\\", "//?/"):
        if cleaned.startswith(prefix):
            return True

    # 2. POSIX special system device prefixes (/dev/, /proc/, /sys/, dev/, proc/, sys/)
    for dev_prefix in ("/dev/", "dev/", "/proc/", "proc/", "/sys/", "sys/"):
        if norm_slash.startswith(dev_prefix):
            return True
    if norm_slash in ("/dev", "dev", "/proc", "proc", "/sys", "sys"):
        return True

    # 3. Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) with or without extensions
    segments = [seg for seg in norm_slash.split("/") if seg]
    for seg in segments:
        base_name = seg.split(".")[0].upper()
        if base_name in BLOCKED_DEVICE_NAMES:
            return True

    # 4. OS filesystem stat mode verification (if path exists on disk, check non-regular special file types)
    try:
        st = os.lstat(os.path.expanduser(cleaned))
        mode = st.st_mode
        if (
            stat.S_ISCHR(mode)
            or stat.S_ISBLK(mode)
            or stat.S_ISFIFO(mode)
            or stat.S_ISSOCK(mode)
        ):
            return True
    except (OSError, ValueError):
        pass

    # 5. Check normalised realpath against dangerous roots if Unix device root is present
    try:
        real_p = os.path.realpath(os.path.expanduser(cleaned))
        for root in ("/dev", "/proc", "/sys"):
            if is_within_boundary(real_p, root):
                return True
    except Exception:
        pass

    return False


def is_sensitive_file(path: str) -> bool:
    """Check if *path* matches any sensitive file pattern."""
    if not path or not path.strip() or is_content_not_path(path):
        return False
    try:
        path_obj = Path(path)
        abs_path = str(path_obj.absolute())
        file_name = path_obj.name
    except Exception:
        return False

    for pattern in SENSITIVE_FILE_PATTERNS:
        if fnmatch(abs_path, pattern):
            return True
        file_pattern = pattern.replace("**/", "")
        if fnmatch(file_name, file_pattern):
            return True
    return False


def is_protected_instruction_file(path: str) -> bool:
    """Check if *path* refers to a protected instruction file (case-insensitive & normalised).

    Protected instruction files steer the future persona and behavioral guardrails
    of AI agents (e.g. AGENTS.md, SOUL.md, .cursorrules). Modifications to these files
    are high-risk persistence vectors for indirect prompt injection and MUST
    require human approval.
    """
    if not path or not str(path).strip() or is_content_not_path(path):
        return False
    try:
        path_obj = Path(path)
        file_name_folded = path_obj.name.casefold()

        try:
            resolved_path = str(path_obj.resolve()).replace("\\", "/")
        except Exception:
            resolved_path = str(path_obj.absolute()).replace("\\", "/")

        resolved_folded = resolved_path.casefold()

        for pattern in PROTECTED_INSTRUCTION_PATTERNS:
            pattern_folded = pattern.casefold()
            if fnmatch(resolved_folded, pattern_folded):
                return True
            file_pattern = pattern_folded.replace("**/", "")
            if fnmatch(file_name_folded, file_pattern):
                return True
            norm_relative = str(path_obj).replace("\\", "/").casefold()
            if fnmatch(norm_relative, pattern_folded):
                return True
    except Exception:
        return False
    return False


def is_evidence_readonly_file(path: str) -> bool:
    """Check if *path* falls under a protected session evidence or user input directory.

    Evidence directories (e.g. `evidence/`, `user_inputs/`) store read-only raw factual
    sources pulled by tools or provided by users. The Agent must NOT overwrite or modify
    these raw materials during multi-step execution.
    """
    if not path or not str(path).strip() or is_content_not_path(path):
        return False
    try:
        path_obj = Path(path)
        abs_norm = str(path_obj.absolute()).replace("\\", "/")
        norm_relative = str(path_obj).replace("\\", "/")

        for pattern in EVIDENCE_READONLY_PATTERNS:
            if fnmatch(abs_norm, pattern) or fnmatch(norm_relative, pattern):
                return True
            pattern_tail = pattern.replace("**/", "")
            if fnmatch(norm_relative, pattern_tail) or fnmatch(path_obj.name, pattern_tail):
                return True
    except Exception:
        return False
    return False

