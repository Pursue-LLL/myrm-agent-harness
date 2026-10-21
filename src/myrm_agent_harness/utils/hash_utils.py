"""统一的哈希工具函数

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- hashlib::hashlib (POS: Python 标准库，哈希算法)
- langchain_core.documents::Document (POS: LangChain 文档类型)
- document_utils::extract_original_content (POS: 文档内容提取工具)
- lru_cache::LRUCache (POS: LRU 缓存实现)

[OUTPUT]
- get_content_hash(): 统一的内容哈希计算函数（支持多种策略和缓存）
- _hash_cache: 全局哈希缓存（LRU，10000项，TTL 2小时）

[POS]
Unified hash utilities. High-performance document content hashing with multiple strategies (md5, sha256, blake2b) and caching.

"""

from __future__ import annotations

import hashlib
import logging
from typing import Literal

from langchain_core.documents import Document

from myrm_agent_harness.utils.document_utils import extract_original_content
from myrm_agent_harness.utils.lru_cache import LRUCache

# 配置日志
logger = logging.getLogger(__name__)

# 全局hash缓存 - 使用LRU缓存避免内存无限增长
_hash_cache: LRUCache[str] = LRUCache(maxsize=10000, ttl=7200)


HashStrategy = Literal["md5", "sha256", "blake2b", "builtin"]


def get_content_hash(
    content: str | Document,
    strategy: HashStrategy = "blake2b",
    use_cache: bool = True,
    clean_content: bool = False,
) -> str:
    """统一的内容哈希计算函数

    Args:
        content: 内容字符串或Document对象
        strategy: 哈希策略
        use_cache: 是否使用缓存
        clean_content: 是否清理内容（去除元信息）

    Returns:
        哈希值字符串
    """
    # 提取文本内容
    if isinstance(content, Document):
        text_content = content.page_content
        # 检查Document元数据中的缓存
        if use_cache and not clean_content:
            cached_hash = content.metadata.get("content_hash")
            if cached_hash:
                return cached_hash
    else:
        text_content = content

    # 内容清理
    if clean_content:
        text_content = extract_original_content(text_content)

    # 生成缓存键
    cache_key = f"{strategy}:{clean_content}:{hash(text_content)}"

    # 检查全局缓存
    if use_cache:
        result = _hash_cache.get(cache_key)
        if result is not None:
            return result

    # 计算哈希
    result = _compute_hash(text_content, strategy)

    # 更新缓存
    if use_cache:
        _hash_cache.set(cache_key, result)

        # 如果是Document对象，也缓存到元数据中
        if isinstance(content, Document) and not clean_content:
            content.metadata["content_hash"] = result

    return result


def _compute_hash(content: str, strategy: HashStrategy) -> str:
    """计算内容哈希值

    Args:
        content: 内容字符串
        strategy: 哈希策略

    Returns:
        哈希值字符串
    """
    if not content:
        return ""

    if strategy == "md5":
        return hashlib.md5(content.encode("utf-8")).hexdigest()
    elif strategy == "sha256":
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    elif strategy == "blake2b":
        return hashlib.blake2b(content.encode("utf-8"), digest_size=16).hexdigest()
    elif strategy == "builtin":
        return str(hash(content))
    else:
        raise ValueError(f"Unsupported hash strategy: {strategy}")


def get_document_dedup_hash(doc: Document) -> str:
    """获取文档去重哈希（带元数据缓存）

    专门用于文档去重，使用清理后的内容计算哈希

    Args:
        doc: Document对象

    Returns:
        去重哈希值
    """
    # 优先使用预存储的hash
    cached_hash = doc.metadata.get("original_content_hash")
    if cached_hash:
        return cached_hash

    # 计算并缓存到元数据中
    computed_hash = get_content_hash(doc, strategy="builtin", clean_content=True, use_cache=False)
    doc.metadata["original_content_hash"] = computed_hash
    return computed_hash


def clear_hash_cache():
    """清空哈希缓存"""
    _hash_cache.clear()
    logger.warning("Hash cache cleared")


def get_cache_stats() -> dict[str, int | list[str]]:
    """获取缓存统计信息"""
    return {
        "cache_size": len(_hash_cache),
        "cache_keys": list(_hash_cache._cache.keys())[:10],
        "max_size": _hash_cache.maxsize,
        "ttl": _hash_cache.ttl,
    }
