"""文本处理工具函数

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- re::re (POS: Python 正则表达式库)

[OUTPUT]
- detect_language(): 检测文本的主要语言类型（chinese/english/mixed）
- is_cross_language(): 检测查询和文档是否跨语言（用于 BM25 fallback 判断）
- preheat_tiktoken(): 预热 tiktoken 编码器（消除冷启动风险）
- get_token_count(): 使用 tiktoken 精确计算 token 数量
- estimate_tokens_fast(): 快速估算 token 数量（无需 tiktoken）
- truncate_text_to_tokens(): 将文本截断到指定 token 数量（简单截断，不考虑句子边界）
- find_sentence_boundary(): 查找最后的句子边界位置
- truncate_by_tokens_with_boundary(): 基于 token 数智能截断（在句子边界处切割）
- smart_truncate(): Head+Tail 智能截断，自动检测尾部诊断信息并调整比例
- has_important_tail(): 检测文本尾部是否包含关键诊断信息
- strip_internal_markers(): 剥离 LLM 输出中意外回显的内部安全边界标记
- strip_ansi(): 剥离终端 ANSI 转义序列（ECMA-48 全规格）
- sanitize_binary_output(): 检测并替换二进制输出（不可打印字符密度超 10%）
- unwrap_markdown_fence(): 剥离 LLM 意外包裹的 Markdown 代码围栏

[POS]
Text processing utilities. Provides token counting, language detection, smart truncation, and output sanitization.

"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document

logger = logging.getLogger(__name__)


def detect_language(text: str) -> str:
    """检测文本的主要语言类型

    Args:
        text: 待检测的文本

    Returns:
        'chinese': 中文为主
        'english': 英文为主
        'mixed': 中英文混合
    """
    if not text or not isinstance(text, str):
        return "english"

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r'[a-zA-Z0-9\s\.,;:!?()\[\]{}"\'-]', text))

    total_chars = len(text.strip())
    if total_chars == 0:
        return "english"

    chinese_ratio = chinese_chars / total_chars
    english_ratio = english_chars / total_chars

    if chinese_chars > 0 and english_chars > 0:
        min_chars = min(chinese_chars, english_chars)
        max_chars = max(chinese_chars, english_chars)

        if min_chars >= 2 and min_chars >= max_chars * 0.3:
            return "mixed"
        elif chinese_chars > english_chars:
            return "chinese" if chinese_ratio > 0.7 else "mixed"
        else:
            return "english" if english_ratio > 0.7 else "mixed"
    elif chinese_chars > 0:
        return "chinese"
    else:
        return "english"


def is_cross_language(
    queries: list[str],
    documents: list[Document],
    sample_length: int = 200,
) -> bool:
    """检测查询和文档是否跨语言（用于 BM25 零召回时的 fallback 判断）

    当 BM25 检索返回 0 结果时，判断是否因为查询和文档语言不匹配导致。
    如果是跨语言场景，应该 fallback 到语义检索（Reranker）或返回原始文档顺序。

    Args:
        queries: 查询列表
        documents: 文档列表
        sample_length: 文档采样长度（默认200字符，平衡性能和准确性）

    Returns:
        True: 查询和文档语言不匹配（跨语言）
        False: 同语言或包含 mixed（不确定）
    """
    if not documents or not queries:
        return False

    query_text = " ".join(queries)
    query_lang = detect_language(query_text)

    doc_sample = " ".join(doc.page_content[:sample_length] for doc in documents[:3])
    doc_lang = detect_language(doc_sample)

    return query_lang != doc_lang and "mixed" not in (query_lang, doc_lang)


def preheat_tiktoken(encoding_name: str = "o200k_base") -> bool:
    """Pre-load tiktoken BPE encoding to eliminate cold-start event-loop blocking.

    tiktoken lazily downloads BPE data (~1.6 MB) from Azure CDN on first use.
    In environments with slow or no internet (China mainland, corporate VPN,
    fresh Docker containers), this synchronous download blocks the async event
    loop for seconds to minutes.  Calling this once at startup moves the cost
    to the startup phase where blocking is acceptable.

    Returns True if preheat succeeded, False if tiktoken is unavailable.
    """
    try:
        import tiktoken

        tiktoken.get_encoding(encoding_name)
        logger.info("tiktoken preheat OK (encoding=%s)", encoding_name)
        return True
    except Exception:
        logger.warning(
            "tiktoken preheat failed (encoding=%s); fast character-ratio estimation will be used as fallback",
            encoding_name,
            exc_info=True,
        )
        return False


def get_token_count(text: str, encoding_name: str = "o200k_base") -> int:
    """使用tiktoken计算文本的Token数量

    Args:
        text: 待计算的文本
        encoding_name: tiktoken编码器名称

    Returns:
        Token数量
    """
    if not text:
        return 0

    try:
        import tiktoken

        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text, disallowed_special=()))
    except Exception as e:
        logger.warning("tiktoken failed, using fast estimation (error: %s)", e)
        return estimate_tokens_fast(text)


def estimate_tokens_fast(text: str) -> int:
    """快速估算Token数量

    Args:
        text: 待估算的文本

    Returns:
        估算的Token数量
    """
    if not isinstance(text, str) or not text:
        return 0

    start_time = time.time()

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    total_chars = len(text)

    if total_chars > 0 and (cjk_chars / total_chars) > 0.2:
        estimated_tokens = int(total_chars * 1.3)
    else:
        estimated_tokens = int(total_chars / 3.5)

    elapsed = time.time() - start_time
    logger.debug(f"快速估算完成: {total_chars}字符 -> {estimated_tokens}Token, 耗时: {elapsed * 1000:.2f}ms")

    return estimated_tokens


_SENTENCE_ENDINGS = ("\n\n", "。", "！", "？", ". ", "! ", "? ", "\n", ".")


def find_sentence_boundary(text: str, min_threshold: float) -> int:
    """查找最后的句子边界位置。

    在 text 中从右向左搜索句子结束符，返回 >= min_threshold 比例处的最远边界。

    Args:
        text: 文本内容。
        min_threshold: 最小保留比例 (0.0-1.0)。

    Returns:
        边界位置（含结束符长度），-1 表示未找到。
    """
    min_pos = int(len(text) * min_threshold)
    best_pos = -1
    for ending in _SENTENCE_ENDINGS:
        pos = text.rfind(ending)
        if pos > min_pos and pos > best_pos:
            best_pos = pos + len(ending)
    return best_pos


def truncate_text_to_tokens(text: str, max_tokens: int, encoding_name: str = "o200k_base") -> str:
    """将文本截断到指定的 token 数量（简单截断，不考虑句子边界）。

    Args:
        text: 待截断的文本。
        max_tokens: 最大 token 数量。
        encoding_name: 编码器名称。

    Returns:
        截断后的文本。
    """
    if not text or max_tokens <= 0:
        return ""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding(encoding_name)
        tokens = encoding.encode(text, disallowed_special=())
        if len(tokens) <= max_tokens:
            return text
        return encoding.decode(tokens[:max_tokens])
    except Exception as e:
        logger.warning(f"Token truncation failed, using character fallback: {e}")
        return _char_fallback_truncate(text, max_tokens)


def truncate_by_tokens_with_boundary(text: str, max_tokens: int, encoding_name: str = "o200k_base") -> str:
    """基于 token 数智能截断（在句子边界处切割）。

    优先在句子边界处截断以保持可读性；tiktoken 失败时退回字符估算。

    Args:
        text: 原始文本。
        max_tokens: 最大 token 数。
        encoding_name: tiktoken 编码器名称。

    Returns:
        截断后的文本。
    """
    if not text or max_tokens <= 0:
        return ""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding(encoding_name)
        tokens = encoding.encode(text, disallowed_special=())
        if len(tokens) <= max_tokens:
            return text
        token_truncated = encoding.decode(tokens[:max_tokens])
        if (boundary := find_sentence_boundary(token_truncated, 0.8)) > 0:
            return token_truncated[:boundary].rstrip()
        return token_truncated
    except Exception as e:
        logger.warning(f"Token truncation failed, using character fallback: {e}")
        max_chars = _estimate_max_chars(text, max_tokens)
        truncated = text[:max_chars]
        if (boundary := find_sentence_boundary(truncated, 0.6)) > 0:
            return truncated[:boundary].rstrip()
        return truncated.rstrip() + "..."


def _char_fallback_truncate(text: str, max_tokens: int) -> str:
    """Character-based fallback when tiktoken is unavailable."""
    max_chars = _estimate_max_chars(text, max_tokens)
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


def _estimate_max_chars(text: str, max_tokens: int) -> int:
    """Estimate max characters from token budget based on CJK ratio."""
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    total_chars = len(text)
    if total_chars > 0 and (cjk_chars / total_chars) > 0.2:
        return int(max_tokens * 1.5)
    return int(max_tokens * 4)


_TAIL_DIAGNOSTIC_PATTERN = re.compile(
    r"\b(error|exception|traceback|panic|failed|fatal|errno|exit.?code|return.?code)\b",
    re.IGNORECASE,
)
_TAIL_STRUCTURAL_END = re.compile(r"[}\]]\s*$")
_TAIL_SUMMARY_PATTERN = re.compile(
    r"\b(total|summary|result|complete|finished|done|passed|rows)\b",
    re.IGNORECASE,
)
_TAIL_CHECK_CHARS = 2000


def has_important_tail(text: str) -> bool:
    """Detect whether text tail contains critical diagnostic information.

    Checks the last ~2000 chars for error patterns, structural closures
    (JSON/array end), and summary lines that should be preserved during
    truncation.
    """
    tail = text[-_TAIL_CHECK_CHARS:]
    return bool(
        _TAIL_DIAGNOSTIC_PATTERN.search(tail)
        or _TAIL_STRUCTURAL_END.search(tail.rstrip())
        or _TAIL_SUMMARY_PATTERN.search(tail)
    )


def smart_truncate(
    text: str,
    max_chars: int,
    *,
    tail_ratio: float = 0.3,
    important_tail_ratio: float = 0.6,
) -> str:
    """Head+Tail truncation with intelligent tail detection.

    When the tail contains error diagnostics, JSON closures, or summary lines,
    automatically shifts the budget toward the tail to preserve them.
    Cuts at newline boundaries to avoid splitting lines.

    Args:
        text: Text to truncate.
        max_chars: Maximum character budget (including marker).
        tail_ratio: Fraction of budget allocated to tail (default 30%).
        important_tail_ratio: Tail fraction when diagnostics detected (default 60%).
    """
    if len(text) <= max_chars:
        return text

    total = len(text)
    marker = f"\n\n[Truncated: {total} chars -> first {{head}} + last {{tail}}]\n\n"
    marker_overhead = len(marker) + 20
    budget = max(200, max_chars - marker_overhead)

    ratio = max(tail_ratio, important_tail_ratio) if has_important_tail(text) else tail_ratio
    tail_budget = int(budget * ratio)
    head_budget = budget - tail_budget

    head_cut = head_budget
    nl = text.rfind("\n", 0, head_budget)
    if nl > head_budget * 0.8:
        head_cut = nl

    tail_start = total - tail_budget
    nl = text.find("\n", tail_start)
    if nl != -1 and nl < tail_start + int(tail_budget * 0.2):
        tail_start = nl + 1

    head_part = text[:head_cut]
    tail_part = text[tail_start:]
    filled_marker = f"\n\n[Truncated: {total} chars -> first {len(head_part)} + last {len(tail_part)}]\n\n"
    return head_part + filled_marker + tail_part


# ---------------------------------------------------------------------------
# Markdown code fence unwrapping
# ---------------------------------------------------------------------------

_LANG_TAG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def unwrap_markdown_fence(text: str) -> str:
    """Strip a single Markdown code fence wrapping the entire text.

    LLMs with unreliable function-calling may wrap commands in fences
    (e.g. ``\\`\\`\\`bash\\nls -la\\n\\`\\`\\``) causing execution failure.
    This safely extracts the inner content when the *entire* text is a
    single fenced block.

    Safety: uses line-based checks (no regex) to avoid ReDoS risk.
    Returns the original text unchanged when the structure does not match.
    """
    if not text:
        return text
    trimmed = text.strip()
    if not trimmed.startswith("```"):
        return text

    lines = trimmed.splitlines()
    if len(lines) < 3:
        return text

    first_line = lines[0].strip()
    if not (
        first_line == "```" or (first_line.startswith("```") and all(c in _LANG_TAG_CHARS for c in first_line[3:]))
    ):
        return text

    if lines[-1].strip() != "```":
        return text

    body = "\n".join(lines[1:-1])
    if not body.strip():
        return text
    return body


# ---------------------------------------------------------------------------
# ANSI escape sequence stripping (ECMA-48 full specification)
# ---------------------------------------------------------------------------

_ANSI_ESCAPE_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"  # CSI (incl. private-mode ?, colon params)
    r"|\][\s\S]*?(?:\x07|\x1b\\)"  # OSC (BEL or ST terminator)
    r"|[PX^_][\s\S]*?(?:\x1b\\)"  # DCS / SOS / PM / APC strings
    r"|[\x20-\x2f]+[\x30-\x7e]"  # nF multi-byte escapes
    r"|[\x30-\x7e]"  # Fp / Fe / Fs single-byte escapes
    r")"
    r"|\x9b[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"  # 8-bit CSI
    r"|\x9d[\s\S]*?(?:\x07|\x9c)"  # 8-bit OSC
    r"|[\x80-\x9f]",  # Other 8-bit C1 control characters
    re.DOTALL,
)

_HAS_ESCAPE_BYTE = re.compile(r"[\x1b\x80-\x9f]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal output (ECMA-48 full spec).

    Covers CSI, OSC, DCS/SOS/PM/APC, nF, Fp/Fe/Fs, and 8-bit C1 variants.
    Fast-path: returns input unchanged when no ESC or C1 bytes are present.
    """
    if not text or not _HAS_ESCAPE_BYTE.search(text):
        return text
    return _ANSI_ESCAPE_RE.sub("", text)


# ---------------------------------------------------------------------------
# Binary output detection and sanitization
# ---------------------------------------------------------------------------

_BINARY_SAMPLE_SIZE = 512
_BINARY_THRESHOLD = 0.10
_PRINTABLE_EXTRAS = frozenset("\n\r\t")


def sanitize_binary_output(text: str) -> str:
    """Replace binary output with a descriptive placeholder.

    Detects high density of non-printable characters (excluding newline,
    carriage return, tab) in the first 512 bytes. Threshold is 10% —
    safe margin since normal text is <1% after ANSI stripping and true
    binary files are typically >30%.

    Must be called **after** ``strip_ansi`` so that legitimate escape
    sequences don't inflate the non-printable count.

    Returns the original text unchanged when content is not binary.
    """
    if not text:
        return text

    sample = text[:_BINARY_SAMPLE_SIZE]
    non_printable = sum(1 for ch in sample if not ch.isprintable() and ch not in _PRINTABLE_EXTRAS)

    if non_printable / len(sample) < _BINARY_THRESHOLD:
        return text

    return f"[Binary output detected ({len(text.encode('utf-8', errors='replace'))} bytes). Use file_read_tool to inspect the file.]"


# ---------------------------------------------------------------------------
# Internal security marker stripping
# ---------------------------------------------------------------------------

_INTERNAL_MARKER_RE = re.compile(
    r"<<<(?:UNTRUSTED_DATA|END_UNTRUSTED_DATA|TOOL_OUTPUT|END_TOOL_OUTPUT)"
    r'(?:\s+id="[^"]{1,128}")?\s*>>>',
    re.IGNORECASE,
)
_SANITIZED_PLACEHOLDER_RE = re.compile(r"\[\[SANITIZED\]\]")


def strip_internal_markers(text: str) -> str:
    """Remove internal security boundary markers from LLM output.

    LLM context uses <<<UNTRUSTED_DATA>>>, <<<TOOL_OUTPUT>>>, and
    [[SANITIZED]] markers for security isolation. If the model
    accidentally echoes them in its final answer, this function
    strips them so end users never see internal plumbing.
    """
    if not text:
        return text
    cleaned = _INTERNAL_MARKER_RE.sub("", text)
    cleaned = _SANITIZED_PLACEHOLDER_RE.sub("", cleaned)
    if cleaned != text:
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned
