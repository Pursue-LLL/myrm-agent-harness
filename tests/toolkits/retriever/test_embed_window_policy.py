"""Tests for embed window policy and embed-budget splitting."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import _fit_text_for_embedding
from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import CloudEmbedding
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedInputTooLargeError,
    EmbedWindowPolicy,
    estimate_wordpiece_tokens,
    is_cjk_wordpiece_model,
    resolve_embed_window_policy,
    token_counter_for_model,
)
from myrm_agent_harness.toolkits.retriever.splitter.embed_budget import split_for_embedding
from myrm_agent_harness.toolkits.wiki.retrieval.vector_chunks import (
    _validate_chunks_fit_window,
    collapse_vector_hits,
    upsert_text_vectors,
)
from myrm_agent_harness.utils.text_utils import get_token_count


class TestEmbedWindowPolicy:
    def test_openai_model_window(self) -> None:
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        assert policy.max_input_tokens == 8191
        assert policy.effective_chunk_budget < policy.max_input_tokens

    def test_unknown_model_conservative_default(self) -> None:
        policy = EmbedWindowPolicy.for_model("unknown-local-embed")
        assert policy.max_input_tokens == 512

    def test_cloud_embedding_exposes_input_limit(self) -> None:
        service = CloudEmbedding(model="text-embedding-3-small", api_key="test")
        assert service.input_token_limit == 8191
        assert resolve_embed_window_policy(service).max_input_tokens == 8191

    def test_unknown_embedding_object_falls_back_to_default_window(self) -> None:
        # An embedding object exposing neither input_token_limit nor a _model must
        # still yield a usable conservative policy (512-token default).
        class _UnknownEmbedding:
            pass

        policy = resolve_embed_window_policy(_UnknownEmbedding())  # type: ignore[arg-type]
        assert policy.max_input_tokens == 512

    def test_model_only_embedding_uses_model_window(self) -> None:
        # An embedding object exposing only _model (no input_token_limit) resolves
        # its policy from the model name's known window.
        class _ModelOnlyEmbedding:
            _model = "BAAI/bge-large-zh-v1.5"

        policy = resolve_embed_window_policy(_ModelOnlyEmbedding())  # type: ignore[arg-type]
        assert policy.model == "BAAI/bge-large-zh-v1.5"
        assert policy.max_input_tokens == 512


class TestCjkWordpieceBudget:
    def test_small_window_model_uses_conservative_margin(self) -> None:
        # bge-large-zh-v1.5 (512 window, BERT wordpiece) uses the 0.5 margin: the
        # effective budget is 256 characters (one CJK char == one wordpiece token),
        # keeping every chunk within the 512-token provider window.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        assert policy.max_input_tokens == 512
        assert policy.effective_chunk_budget == 256

    def test_large_bpe_model_keeps_standard_margin(self) -> None:
        # text-embedding-3-small is BPE and safe at 0.9 margin.
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        assert policy.effective_chunk_budget == int(8191 * 0.9)

    def test_cjk_wordpiece_model_detection(self) -> None:
        assert is_cjk_wordpiece_model("BAAI/bge-large-zh-v1.5")
        assert is_cjk_wordpiece_model("netease-youdao/bce-embedding-base_v1")
        assert is_cjk_wordpiece_model("BAAI/bge-m3")
        assert is_cjk_wordpiece_model("nomic-embed-text")
        assert not is_cjk_wordpiece_model("text-embedding-3-small")
        assert not is_cjk_wordpiece_model(None)

    def test_wordpiece_estimate_upper_bounds_cjk(self) -> None:
        # 390 CJK chars estimate to >= 390 wordpiece tokens (never undercounts).
        text = "深度检索质量保障机制" * 30
        assert estimate_wordpiece_tokens(text) >= len(text)

    def test_wordpiece_estimate_mixed_scripts(self) -> None:
        # Mixed CJK+latin text: CJK chars count 1:1, latin ~4 chars/token rounded up.
        text = "中文abc中文def中文"
        assert estimate_wordpiece_tokens(text) >= 6  # 6 CJK chars -> >= 6 tokens
        assert estimate_wordpiece_tokens("abc") == 1  # 3 latin chars -> 1 token
        assert estimate_wordpiece_tokens("") == 0

    def test_wordpiece_estimate_counts_korean_and_kana(self) -> None:
        # Hangul/Hiragana/Katakana are 1 char == 1 token for wordpiece tokenizers,
        # while o200k undercounts them (~2 chars/token). Each must count 1:1.
        assert estimate_wordpiece_tokens("안녕하세요") == 5
        assert estimate_wordpiece_tokens("こんにちは") == 5
        assert estimate_wordpiece_tokens("コンニチハ") == 5
        # Mixed: Hangul 1:1, latin folded into the 4 chars/token ratio.
        assert estimate_wordpiece_tokens("한국어abc") >= 3

    def test_wordpiece_estimate_counts_cjk_extension_blocks(self) -> None:
        # CJK Extension A and Compatibility blocks are also single-token chars.
        assert estimate_wordpiece_tokens("\U00020000") == 1  # Extension A
        assert estimate_wordpiece_tokens("\uF900") == 1  # Compatibility

    def test_wordpiece_estimate_counts_cjk_punctuation(self) -> None:
        # CJK punctuation (U+3000-303F) and fullwidth forms (U+FF00-FFEF: ！？）
        # also map to one wordpiece token; counting them at the 1/4 latin ratio
        # would undercount punctuation-heavy CJK text and break the
        # conservative-upper-bound contract of the estimate.
        assert estimate_wordpiece_tokens("你好，世界。") == len("你好，世界。")
        assert estimate_wordpiece_tokens("。！？") == 3
        assert estimate_wordpiece_tokens("hello，world") == 4  # 逗号 1 + 10 latin / 4

    def test_bge_m3_large_window_uses_standard_margin(self) -> None:
        # bge-m3 (XLM-R 250k) has measured char/token < 1 across zh/ja/ko/en, so its
        # character-count budget can use the standard 0.9 margin (7372 chars) without
        # risking window overflow.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-m3")
        assert policy.max_input_tokens == 8192
        assert policy.effective_chunk_budget == int(8192 * 0.9)

    def test_nomic_2048_window_keeps_conservative_margin(self) -> None:
        # nomic-embed-text is a BERT wordpiece model (2048 window) -> 0.5 margin.
        policy = EmbedWindowPolicy.for_model("nomic-embed-text")
        assert policy.max_input_tokens == 2048
        assert policy.effective_chunk_budget == 1024
        assert is_cjk_wordpiece_model("nomic-embed-text")

    def test_minilm_and_e5_wordpiece_detection(self) -> None:
        # MiniLM/e5/paraphrase/jina-v2 are BERT/XLM wordpiece families; treating
        # them as BPE would budget on o200k tokens, which undercounts their real
        # wordpiece input and silently truncates at the provider.
        assert is_cjk_wordpiece_model("sentence-transformers/all-MiniLM-L6-v2")
        assert is_cjk_wordpiece_model("all-MiniLM-L12-v2")
        assert is_cjk_wordpiece_model("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        assert is_cjk_wordpiece_model("intfloat/multilingual-e5-large")
        assert is_cjk_wordpiece_model("jina-embeddings-v2-base-zh")
        assert is_cjk_wordpiece_model("gte-large-zh")
        assert is_cjk_wordpiece_model("e5-base-v2")
        assert is_cjk_wordpiece_model("sentence-transformers/all-mpnet-base-v2")
        assert is_cjk_wordpiece_model("xlm-roberta-base")
        assert is_cjk_wordpiece_model("sentence-transformers/all-distilroberta-v1")
        assert not is_cjk_wordpiece_model("text-embedding-3-small")
        assert not is_cjk_wordpiece_model("Qwen/Qwen3-Embedding-8B")
        assert not is_cjk_wordpiece_model(None)

    def test_minilm_window_budget(self) -> None:
        # all-MiniLM-L6-v2 is a BERT wordpiece model with a 256-token window -> 0.5
        # margin yields a 128-character budget (one CJK char == one token).
        policy = EmbedWindowPolicy.for_model("sentence-transformers/all-MiniLM-L6-v2")
        assert policy.max_input_tokens == 256
        assert policy.effective_chunk_budget == 128
        assert is_cjk_wordpiece_model("sentence-transformers/all-MiniLM-L6-v2")

    def test_minilm_cjk_chunk_never_exceeds_window(self) -> None:
        # A CJK text split for all-MiniLM-L6-v2 must never exceed its 256-token
        # provider window; the 128-character budget keeps every chunk at or below
        # 128 wordpiece tokens.
        policy = EmbedWindowPolicy.for_model("sentence-transformers/all-MiniLM-L6-v2")
        text = "深度检索质量保障机制的动态窗口预算测试。" * 60
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= policy.effective_chunk_budget
            assert estimate_wordpiece_tokens(chunk) <= policy.max_input_tokens

    def test_cjk_long_text_never_exceeds_small_window(self) -> None:
        # A long CJK text split for bge-large-zh-v1.5 must produce chunks whose
        # wordpiece estimate never exceeds the 512-token provider window.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        paragraphs = [
            f"第{i}节：深度检索质量保障机制需要动态调整嵌入预算窗口大小，确保中文长文本不会在模型输入上限处被静默截断。"
            for i in range(20)
        ]
        text = "\n\n".join(paragraphs)
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert estimate_wordpiece_tokens(chunk) <= policy.max_input_tokens


class TestSplitForEmbedding:
    def test_short_text_single_chunk(self) -> None:
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        text = "Short wiki truth section."
        chunks = split_for_embedding(text, policy)
        assert chunks == [text]

    def test_long_text_multiple_chunks(self) -> None:
        # bge-large-zh is a wordpiece model whose budget is a character count, so
        # each chunk must stay within the character budget (o200k tokens would be
        # the wrong unit for this model).
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        paragraphs = [
            "## Section {}\n\n{}".format(
                i,
                f"Detailed engineering notes about module {i} with extra context." * 20,
            )
            for i in range(20)
        ]
        text = "\n\n".join(paragraphs)
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= policy.effective_chunk_budget

    def test_korean_text_chunks_stay_inside_wordpiece_window(self) -> None:
        # Korean text chunked for bge-large-zh-v1.5 must never exceed the 512-token
        # provider window. The character-count budget caps chunks at 256 chars; even
        # the worst-case Hangul density for this model (~1.86 tokens/char) stays
        # below 512.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        text = "안녕하세요 반갑습니다. 한국어 문서를 청크로 나누는 테스트입니다. " * 60
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= policy.effective_chunk_budget
            assert estimate_wordpiece_tokens(chunk) <= policy.max_input_tokens

    def test_bge_m3_chunks_use_larger_character_budget(self) -> None:
        # bge-m3 budget is a character count at the standard margin (7372 chars);
        # a long CJK text must split into chunks within it.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-m3")
        assert policy.effective_chunk_budget == int(8192 * 0.9)
        text = "深度检索质量保障机制的动态窗口预算测试。" * 500
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= policy.effective_chunk_budget

    def test_wordpiece_oversized_single_line_hard_cut(self) -> None:
        # A single line longer than the character budget (no newlines) must be
        # hard-cut at character boundaries into character-bounded chunks.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        text = "无换行的超长中文单行文本用于验证字符级硬切分。" * 40
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= policy.effective_chunk_budget

    def test_long_text_bpe_path_keeps_budget(self) -> None:
        # BPE models keep the tiktoken-based path; long text must produce chunks
        # within the o200k budget.
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        paragraphs = [
            "## Section {}\n\n{}".format(
                i,
                "Detailed engineering notes about module {} with extra context.".format(i) * 60,
            )
            for i in range(20)
        ]
        text = "\n\n".join(paragraphs)
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert get_token_count(chunk) <= policy.effective_chunk_budget

    def test_empty_text_returns_no_chunks(self) -> None:
        # Whitespace-only input strips to nothing and must produce no chunks.
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        assert split_for_embedding("", policy) == []
        assert split_for_embedding("   \n\t ", policy) == []

    def test_text_chunker_empty_result_falls_back_to_source(self, monkeypatch) -> None:
        # If TextChunker yields no docs (e.g. an unparseable input), the chunker
        # must fall back to the source text and still bound it to the budget, so
        # content is never dropped and never exceeds the provider window.
        from myrm_agent_harness.toolkits.retriever.splitter import embed_budget as _embed_budget

        class _EmptyChunker:
            def chunk_text(self, *args: object, **kwargs: object) -> list[object]:
                return []

        monkeypatch.setattr(
            _embed_budget, "TextChunker", lambda *a, **k: _EmptyChunker()  # type: ignore[no-any-return]
        )
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        text = "long" * 40000  # ~40000 o200k tokens — over budget, so the chunker runs
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert get_token_count(chunk) <= policy.effective_chunk_budget

    def test_enforce_chunk_budget_recursive_hard_cut_single_line(self) -> None:
        # A single line without newlines that still exceeds the token budget (e.g.
        # one huge word that the splitter keeps whole) must be bisected recursively
        # until every part fits. This guards the BPE path when line-based splitting
        # cannot make progress.
        from myrm_agent_harness.toolkits.retriever.splitter.embed_budget import _enforce_chunk_budget

        budget = 7371
        text = "x" * 70000  # ~8750 o200k tokens in one line
        parts = _enforce_chunk_budget(text, budget)
        assert len(parts) >= 2
        for part in parts:
            assert get_token_count(part) <= budget

    def test_enforce_chunk_budget_multiline_recursive(self) -> None:
        # When line-based splitting produces several lines that each still exceed
        # the budget, every line must be bounded recursively as well.
        from myrm_agent_harness.toolkits.retriever.splitter.embed_budget import _enforce_chunk_budget

        budget = 7371
        text = "x" * 70000 + "\n" + "y" * 70000  # 两行，每行 ~8750 tokens
        parts = _enforce_chunk_budget(text, budget)
        assert len(parts) >= 4
        for part in parts:
            assert get_token_count(part) <= budget


class TestMemoryTruncationExplicit:
    def test_fit_text_truncates_oversized_memory(self) -> None:
        # A memory longer than the small window must be truncated to the first
        # chunk (documented behavior) rather than silently exceeding the window.
        service = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="test")
        text = "这是一条超过嵌入窗口的中文记忆内容。" * 80
        fitted = _fit_text_for_embedding(text, service)
        assert len(fitted) < len(text)
        assert estimate_wordpiece_tokens(fitted) <= service.input_token_limit

    def test_short_memory_preserved_unchanged(self) -> None:
        service = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="test")
        text = "简短的中文记忆。"
        assert _fit_text_for_embedding(text, service) == text


class TestCollapseVectorHits:
    def test_keeps_best_score_per_concept(self) -> None:
        hits = [
            ("Concept/A", 0.4),
            ("Concept/A", 0.9),
            ("Concept/B", 0.7),
        ]
        collapsed = collapse_vector_hits(hits)
        assert collapsed == [("Concept/A", 0.9), ("Concept/B", 0.7)]


class TestTokenCounterForModel:
    def test_wordpiece_model_uses_estimate(self) -> None:
        # Wordpiece models count CJK 1:1; the returned callable must be the
        # wordpiece estimate, not the o200k counter that undercounts CJK.
        counter = token_counter_for_model("BAAI/bge-large-zh-v1.5")
        assert counter is estimate_wordpiece_tokens
        assert counter("你好世界") == 4

    def test_bpe_model_uses_o200k(self) -> None:
        assert token_counter_for_model("text-embedding-3-small") is get_token_count

    def test_unknown_model_falls_back_to_o200k(self) -> None:
        assert token_counter_for_model(None) is get_token_count


class TestWordpieceHeaderAwareChunking:
    def test_markdown_header_starts_new_chunk(self) -> None:
        # A markdown heading must open a chunk: burying "## 第2节" mid-chunk would
        # detach the heading vector from its section content and pollute retrieval.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        sections = []
        for i in range(6):
            body = "\n".join(
                f"第{i}节工程说明细节行{j}，包含足够长的中文描述内容用于测试。" for j in range(6)
            )
            sections.append(f"## 第{i}节标题\n\n{body}")
        text = "\n\n".join(sections)
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.startswith("## ")
            assert len(chunk) <= policy.effective_chunk_budget

    def test_plain_text_chunking_unchanged(self) -> None:
        # Text without markdown headings packs purely by character budget; a single
        # overlong line is still hard-cut at character boundaries.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        text = "没有标题的普通中文段落文本用于验证无标题分块行为不变。" * 40
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= policy.effective_chunk_budget

    def test_code_block_comments_do_not_trigger_header_split(self) -> None:
        # Comment lines inside a ``` fence (e.g. `# config`) must not be treated as
        # markdown headings, mirroring SmartMarkdownHeaderTextSplitter's code-block
        # exclusion; otherwise dense comment blocks fragment chunks needlessly.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        text = (
            "普通正文段落内容填充到较长的长度用于触发分块行为。\n\n"
            "```\n# a\n# b\n# c\n```\n"
            "后续正文内容继续填充到超过预算的长度触发多块。" * 20
        )
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert not chunk.startswith("# ")  # comment lines never open a chunk


class TestValidateChunksFitWindow:
    def test_wordpiece_chunk_fails_loud_when_o200k_would_pass(self) -> None:
        # 600 CJK chars estimate to ~600 wordpiece tokens (> 512) but only ~300
        # o200k tokens (< 512). The guard must use the wordpiece counter or it
        # would silently pass an oversized chunk to the provider.
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        oversized = "深度检索质量保障机制" * 60
        assert get_token_count(oversized) < policy.max_input_tokens
        assert estimate_wordpiece_tokens(oversized) > policy.max_input_tokens
        with pytest.raises(EmbedInputTooLargeError):
            _validate_chunks_fit_window([oversized], policy, "Concept/A")

    def test_fit_chunks_pass(self) -> None:
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        _validate_chunks_fit_window(["简短中文记忆内容。"], policy, "Concept/A")


class _FakeVectorStore:
    def __init__(self) -> None:
        self.upserted_docs: list[object] | None = None
        self.delete_calls = 0

    async def delete_by_filter(self, collection_name: str, filt: dict[str, str]) -> None:
        self.delete_calls += 1

    async def delete(self, collection_name: str, ids: list[str]) -> None:
        self.delete_calls += 1

    async def upsert(self, collection_name: str, docs: list[object]) -> None:
        self.upserted_docs = docs


class _FakeEmbedding:
    _model = "BAAI/bge-large-zh-v1.5"  # wordpiece path exercises character chunking

    def __init__(self) -> None:
        self.last_chunks: list[str] | None = None

    async def embed_batch(self, chunks: list[str]) -> list[list[float]]:
        self.last_chunks = chunks
        return [[0.1, 0.2] for _ in chunks]


class TestUpsertTextVectors:
    @pytest.mark.asyncio
    async def test_empty_text_returns_zero(self) -> None:
        result = await upsert_text_vectors(
            embedding=_FakeEmbedding(),
            vector=_FakeVectorStore(),
            collection_name="wiki_vectors",
            parent_key="Concept/A",
            text="   \n  ",
            base_metadata={"title": "A"},
            metadata_key="parent_key",
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_upsert_single_chunk_with_metadata(self) -> None:
        vec = _FakeVectorStore()
        emb = _FakeEmbedding()
        text = "简短的中文知识条目内容。"
        result = await upsert_text_vectors(
            embedding=emb,
            vector=vec,
            collection_name="wiki_vectors",
            parent_key="Concept/A",
            text=text,
            base_metadata={"title": "A"},
            metadata_key="parent_key",
        )
        assert result == 1
        assert vec.upserted_docs is not None
        doc = vec.upserted_docs[0]
        assert doc.content == text
        assert doc.metadata["parent_key"] == "Concept/A"  # type: ignore[index]
        assert doc.metadata["chunk_index"] == 0  # type: ignore[index]
        assert doc.metadata["chunk_count"] == 1  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_wordpiece_long_text_multi_chunk_upsert(self) -> None:
        # A long CJK text splits into several character-bounded chunks for the
        # wordpiece model; every chunk must be embedded and upserted with a
        # matching chunk_index/chunk_count so retrieval stays aligned.
        vec = _FakeVectorStore()
        emb = _FakeEmbedding()
        text = "深度检索质量保障机制的动态窗口预算测试。" * 60
        result = await upsert_text_vectors(
            embedding=emb,
            vector=vec,
            collection_name="wiki_vectors",
            parent_key="Concept/A",
            text=text,
            base_metadata={"title": "A"},
            metadata_key="parent_key",
        )
        assert result >= 2
        assert emb.last_chunks is not None
        assert len(emb.last_chunks) == result
        assert vec.upserted_docs is not None
        assert len(vec.upserted_docs) == result
        for index, doc in enumerate(vec.upserted_docs):
            assert doc.metadata["chunk_index"] == index  # type: ignore[index]
            assert doc.metadata["chunk_count"] == result  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_batch_size_mismatch_fails_loud(self) -> None:
        class _BadEmbedding:
            async def embed_batch(self, chunks: list[str]) -> list[list[float]]:
                return []  # wrong count: provider returned nothing

        with pytest.raises(RuntimeError, match="batch size mismatch"):
            await upsert_text_vectors(
                embedding=_BadEmbedding(),  # type: ignore[arg-type]
                vector=_FakeVectorStore(),
                collection_name="wiki_vectors",
                parent_key="Concept/A",
                text="Short wiki truth section.",
                base_metadata={"title": "A"},
                metadata_key="parent_key",
            )


class TestCloudEmbeddingValidation:
    @pytest.mark.asyncio
    async def test_rejects_oversized_single_input(self) -> None:
        service = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="test")
        huge = "token " * 2000
        with pytest.raises(EmbedInputTooLargeError):
            await service.embed(huge)

    @pytest.mark.asyncio
    async def test_rejects_cjk_input_over_wordpiece_window(self) -> None:
        # CJK input whose wordpiece estimate exceeds the 512 limit must fail loud,
        # even though its o200k count stays below the limit. ~600 CJK chars map to
        # ~600 wordpiece tokens (>512) but only ~390 o200k tokens (<512).
        service = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="test")
        huge = "这是一段用于验证小窗口嵌入模型输入上限的中文文本内容。" * 24
        assert get_token_count(huge) < service.input_token_limit
        assert estimate_wordpiece_tokens(huge) > service.input_token_limit
        with pytest.raises(EmbedInputTooLargeError):
            await service.embed(huge)

    @pytest.mark.asyncio
    async def test_rejects_korean_input_over_wordpiece_window(self) -> None:
        # Hangul is also 1 char == 1 wordpiece token while o200k undercounts it
        # (~2 chars/token); an oversized Korean input must fail loud.
        service = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="test")
        huge = "안녕하세요 반갑습니다 한국어 텍스트 임베딩 테스트입니다. " * 25
        assert get_token_count(huge) < service.input_token_limit
        assert estimate_wordpiece_tokens(huge) > service.input_token_limit
        with pytest.raises(EmbedInputTooLargeError):
            await service.embed(huge)

    @pytest.mark.asyncio
    async def test_rejects_hiragana_input_over_wordpiece_window(self) -> None:
        # Hiragana is also undercounted by o200k (~1.9 chars/token).
        service = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="test")
        huge = "こんにちはこれはひらがなのテキストです。" * 30
        assert get_token_count(huge) < service.input_token_limit
        assert estimate_wordpiece_tokens(huge) > service.input_token_limit
        with pytest.raises(EmbedInputTooLargeError):
            await service.embed(huge)
