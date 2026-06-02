"""Utility functions.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- runtime.cancellation::CancellationToken (POS: 取消令牌，支持异步任务取消)
- runtime.steering::SteeringToken (POS: Steering 令牌，允许运行时注入消息中断工具链)
- document_utils::parse_front_matter, extract_original_content (POS: 文档解析工具)
- context_format::format_documents_with_metadata, format_crawl_results, wrap_with_* (POS: 上下文格式化工具)
- rwlock::RWLock (POS: 异步读写锁，支持多读单写)

[OUTPUT]
- CancellationToken: 取消令牌
- SteeringToken: Steering 令牌
- RWLock: 异步读写锁
- parse_front_matter, extract_original_content: 文档解析函数
- format_documents_with_metadata, format_crawl_results: 上下文格式化函数
- wrap_with_external_sources_tag, wrap_with_tool_output_tag: 安全边界包装函数（5 层防护）

[POS]
Utility library exports. Public interface for the utils module providing commonly used helper functions.

"""

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    # Runtime utilities
    "CancellationToken": ("myrm_agent_harness.utils.runtime.cancellation", "CancellationToken"),
    "SteeringToken": ("myrm_agent_harness.utils.runtime.steering", "SteeringToken"),
    "RWLock": ("myrm_agent_harness.utils.rwlock", "RWLock"),
    # Document utilities
    "parse_front_matter": ("myrm_agent_harness.utils.document_utils", "parse_front_matter"),
    "extract_original_content": ("myrm_agent_harness.utils.document_utils", "extract_original_content"),
    # Context formatting
    "format_documents_with_metadata": ("myrm_agent_harness.utils.context_format", "format_documents_with_metadata"),
    "format_crawl_results": ("myrm_agent_harness.utils.context_format", "format_crawl_results"),
    "wrap_with_external_sources_tag": ("myrm_agent_harness.utils.context_format", "wrap_with_external_sources_tag"),
    "wrap_with_tool_output_tag": ("myrm_agent_harness.utils.context_format", "wrap_with_tool_output_tag"),
    "TruncationStats": ("myrm_agent_harness.utils.context_format", "TruncationStats"),
    # Network utilities
    "get_local_ip": ("myrm_agent_harness.utils.network", "get_local_ip"),
    # File utilities
    "extract_file_id_from_url": ("myrm_agent_harness.utils.files", "extract_file_id_from_url"),
    # Device fingerprint utilities (legacy, kept for migration compatibility)
    "get_device_fingerprint": ("myrm_agent_harness.utils.device_fingerprint", "get_device_fingerprint"),
    "derive_key_from_fingerprint": ("myrm_agent_harness.utils.device_fingerprint", "derive_key_from_fingerprint"),
    # Encryption key resolution
    "resolve_local_encryption_key": ("myrm_agent_harness.utils.encryption_key", "resolve_local_encryption_key"),
}

__all__ = [
    # Runtime utilities
    "CancellationToken",
    # Concurrency primitives
    "RWLock",
    "SteeringToken",
    "TruncationStats",
    "derive_key_from_fingerprint",
    # File utilities
    "extract_file_id_from_url",
    "extract_original_content",
    "format_crawl_results",
    # Context formatting
    "format_documents_with_metadata",
    # Device fingerprint utilities (legacy)
    "get_device_fingerprint",
    # Network utilities
    "get_local_ip",
    # Document utilities
    "parse_front_matter",
    # Encryption key resolution
    "resolve_local_encryption_key",
    "wrap_with_external_sources_tag",
    "wrap_with_tool_output_tag",
]


def __getattr__(name: str) -> object:
    """Lazily resolve public exports to keep utility imports lightweight."""
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__ + [name for name in globals() if not name.startswith("_")]))
