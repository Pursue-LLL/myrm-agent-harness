"""文件 I/O 资源限制与正则安全配置。

路径安全（危险路径、敏感文件）集中在 ``security.path_security``。
本模块仅包含 I/O 资源限制、正则安全设置和审计开关。

[INPUT]
（无外部依赖）

[OUTPUT]
- FileIOConfig: I/O 资源限制、正则安全、审计日志配置
- DEFAULT_FILE_IO_CONFIG: FileIOConfig 默认实例

[POS]
File I/O configuration. Defines resource limits (concurrent reads, file size caps), regex safety (ReDoS protection), and audit toggles.

"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileIOConfig:
    """Resource limits and safety settings for file operations."""

    # Path constraints
    max_path_depth: int = 20
    """Maximum allowed path depth to prevent deeply nested path attacks."""

    follow_symlinks: bool = False
    """Whether to follow symbolic links (disabled by default for security)."""

    # Resource limits
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    """Maximum file size for read operations."""

    max_concurrent_reads: int = 10
    """Maximum number of concurrent file read operations."""

    max_search_results: int = 100
    """Maximum number of search results to return."""

    max_search_files: int = 1000
    """Maximum number of files to search through."""

    search_timeout_seconds: float = 30.0
    """Maximum time for search operations."""

    # Regex safety
    max_regex_length: int = 500
    """Maximum allowed regex pattern length."""

    regex_timeout_seconds: float = 5.0
    """Maximum time for regex compilation and matching."""

    dangerous_regex_patterns: list[str] = field(
        default_factory=lambda: [
            r"(.+)+",
            r"(.*)*",
            r"(.+)*",
            r"(.*)+",
            r"(\w+\s*)+",
            r"(\d+)*",
        ]
    )
    """Regex patterns likely to cause ReDoS."""

    # Audit
    enable_audit_log: bool = True
    """Whether to enable security audit logging."""

    log_sensitive_operations: bool = True
    """Whether to log operations on sensitive files."""


DEFAULT_FILE_IO_CONFIG = FileIOConfig()
