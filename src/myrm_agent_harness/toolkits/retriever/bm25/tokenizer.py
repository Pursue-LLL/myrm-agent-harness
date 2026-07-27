"""Unified tokenizer service.

Lazy-loaded tokenizer supporting CJK/English hybrid tokenization.

Core capabilities:
- Chinese segmentation: jieba (precise + search-engine modes)
- CJK bigram fallback: character unigram + bigram when jieba unavailable
- English enhancement: zero-dependency stopword + suffix normalization
- Smart detection: auto-identifies mixed CJK/English text

[INPUT]
- retriever.bm25.english_normalizer::normalize_english_token (POS: Zero-dependency English stopword + suffix normalization for BM25)
(no external module dependencies at import time — jieba is lazy-loaded)

[OUTPUT]
TokenizerService: Singleton tokenizer with tokenize method and backend property
get_tokenizer_service: Module-level accessor returning the singleton instance
preload_tokenizer: Async convenience function for startup preloading
_cjk_bigram_tokenize: CJK character unigram+bigram tokenization fallback

[POS]
Tokenization service for BM25 retrieval. Provides language-aware tokenization that feeds
the BM25 inverted index with properly segmented tokens.

"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Literal

from myrm_agent_harness.toolkits.retriever.bm25.english_normalizer import normalize_english_token

logger = logging.getLogger(__name__)

_ENGLISH_WORD_PATTERN = re.compile(r"^[a-zA-Z]([a-zA-Z\-']*[a-zA-Z])?$")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")
_NON_CJK_WORD = re.compile(r"[a-zA-Z0-9]+")


def _cjk_bigram_tokenize(text: str) -> list[str]:
    """Tokenize CJK text into character unigrams + bigrams.

    This is the industry-standard fallback when no proper segmenter (jieba)
    is available. Same approach used by openclaw and CodePilot.

    For input "机器学习模型":
      unigrams: ["机", "器", "学", "习", "模", "型"]
      bigrams:  ["机器", "器学", "学习", "习模", "模型"]
      result:   all combined (enables partial phrase matching in BM25)
    """
    tokens: list[str] = []
    for run_match in _CJK_RUN.finditer(text):
        chars = list(run_match.group())
        tokens.extend(chars)
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i + 1])
    for word_match in _NON_CJK_WORD.finditer(text):
        tokens.append(word_match.group())
    return tokens


class TokenizerService:
    """Unified tokenizer service (singleton).

    Lazy-loads jieba to avoid startup overhead.
    Falls back to CJK bigram tokenization when jieba is unavailable.
    """

    def __init__(self) -> None:
        self._jieba = None
        self._initialized = False

    def _init_jieba_sync(self) -> None:
        """Sync-initialize jieba tokenizer (idempotent)."""
        if self._jieba is not None:
            return

        try:
            import jieba

            jieba_logger = logging.getLogger("jieba")
            jieba_logger.setLevel(logging.WARNING)

            jieba.initialize()
            self._jieba = jieba
            logger.info("jieba tokenizer initialized")
        except (ImportError, TypeError):
            logger.warning("jieba not installed, using CJK bigram fallback")
            self._jieba = None

    @property
    def backend(self) -> str:
        """Return the active tokenization backend name."""
        self._initialize()
        return "jieba" if self._jieba else "bigram_fallback"

    def _initialize(self) -> None:
        """Initialize tokenizer (sync)."""
        if not self._initialized:
            self._init_jieba_sync()
            self._initialized = True

    async def _async_initialize(self) -> None:
        """Initialize tokenizer (async)."""
        if not self._initialized:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._init_jieba_sync)
            self._initialized = True

    def _enhance_english(self, tokens: list[str]) -> list[str]:
        """Apply stopword filtering and suffix normalization to English tokens."""
        result: list[str] = []
        for token in tokens:
            if _ENGLISH_WORD_PATTERN.match(token):
                normalized = normalize_english_token(token)
                if normalized is not None:
                    result.append(normalized)
            else:
                result.append(token)
        return result

    def tokenize(
        self,
        text: str,
        mode: Literal["simple", "search"] = "simple",
        enable_english_enhancement: bool = False,
    ) -> list[str]:
        """Unified tokenization entry point.

        Args:
            text: Input text to tokenize.
            mode: Tokenization mode.
                - simple: precise segmentation (for BM25 index building)
                - search: search-engine mode (higher recall, for queries)
            enable_english_enhancement: Enable English stopword + suffix normalization.

        Returns:
            List of tokens.
        """
        self._initialize()

        if self._jieba:
            if mode == "search":
                tokens = list(self._jieba.cut_for_search(text))
            else:
                tokens = list(self._jieba.cut(text))
        else:
            tokens = _cjk_bigram_tokenize(text)

        tokens = [t for token in tokens if (t := token.strip())]

        if enable_english_enhancement:
            tokens = self._enhance_english(tokens)

        return tokens

    async def preload(self, *, enable_english_enhancement: bool = False) -> None:
        """Async-preload tokenizer (jieba; English normalizer is zero-dep, no preload needed)."""
        _ = enable_english_enhancement
        logger.info("Preloading tokenizer...")
        try:
            await self._async_initialize()
            logger.info("jieba preloaded successfully")
        except Exception as e:
            logger.error(f"Tokenizer preload failed: {e}")
            raise


# Global singleton
_tokenizer_service = TokenizerService()


def get_tokenizer_service() -> TokenizerService:
    """Get the global tokenizer service singleton."""
    return _tokenizer_service


async def preload_tokenizer(enable_english_enhancement: bool = False) -> None:
    """Preload tokenizer at application startup (convenience function)."""
    await _tokenizer_service.preload(enable_english_enhancement=enable_english_enhancement)
