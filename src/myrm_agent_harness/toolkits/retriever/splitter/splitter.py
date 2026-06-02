"""Text splitting utilities.

Provides text splitting for different content types (Markdown, plain text) and strategies.

[INPUT]
retriever.splitter.chunk_processor::detect_content_type (POS: Content-type detection for chunks)
retriever.splitter.chunk_processor::inject_structured_context (POS: Structured-context injection)
retriever.splitter.recursive_character_protect_special_splitter::RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken (POS: Tiktoken-based recursive splitter with special-block protection)
retriever.splitter.smart_markdown_header_text_splitter::SmartMarkdownHeaderTextSplitter (POS: Markdown header-aware splitter)
utils.text_utils::detect_language, get_token_count (POS: Language detection and token counting)

[OUTPUT]
split_text: Splits a document into token-bounded chunks using Markdown-aware or recursive strategy

[POS]
High-level text splitter. Selects the appropriate splitting strategy based on content type
and produces token-bounded Document chunks with contextual metadata.

"""

import logging
import time

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.splitter.chunk_processor import (
    detect_content_type,
    inject_structured_context,
)
from myrm_agent_harness.toolkits.retriever.splitter.recursive_character_protect_special_splitter import (
    RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken,
)
from myrm_agent_harness.toolkits.retriever.splitter.smart_markdown_header_text_splitter import (
    SmartMarkdownHeaderTextSplitter,
)
from myrm_agent_harness.utils.text_utils import detect_language, get_token_count

logger = logging.getLogger(__name__)


def _extract_headers_before_content(full_text: str, split_start_pos: int) -> list[tuple[int, str]]:
    """Extract all Markdown headings before a chunk start position (excluding code blocks).

    Args:
        full_text: Full text
        split_start_pos: Chunk start character position in the full text

    Returns:
        Heading list [(level, title), ...], ordered parent-to-child
    """
    if split_start_pos <= 0:
        return []

    # Only examine text before the chunk
    before_text = full_text[:split_start_pos]
    lines = before_text.split("\n")

    headers = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Detect code block boundaries
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        # Skip content inside code blocks
        if in_code_block:
            continue

        # Detect Markdown headings: must start with # followed by space or heading text
        if stripped.startswith("#") and not stripped.startswith("<!--"):
            # Count # characters
            hash_count = 0
            for ch in stripped:
                if ch == "#":
                    hash_count += 1
                else:
                    break

            # Check character after #: should be space or heading text
            if hash_count > 0 and hash_count <= 6:
                remaining = stripped[hash_count:]
                if not remaining or remaining[0] in (" ", "\t"):
                    # Valid Markdown heading
                    title = remaining.strip()
                    if title:  # Ensure heading is not empty
                        headers.append((hash_count, title))

    if not headers:
        return []

    # Traverse backwards from last heading to build hierarchy path
    result = []
    current_level = headers[-1][0]
    result.append(headers[-1])

    for i in range(len(headers) - 2, -1, -1):
        level, title = headers[i]
        if level < current_level:
            result.insert(0, (level, title))
            current_level = level

    return result


# Text split separators (heading splits handled by SmartMarkdownHeaderTextSplitter)
# Priority high-to-low: headings > list items > paragraphs > sentences > words
# Note: text is normalized by text_cleaner, list format is standardized
# Design principle: preserve semantic integrity, split only between top-level list items
OPTIMIZED_SEPARATORS = [
    # Heading separators (levels 2-5; level 1 handled by SmartMarkdownHeaderTextSplitter)
    "\n## ",
    "\n### ",
    "\n#### ",
    "\n##### ",
    # Paragraph separators
    "\n\n",
    "\n",
    # Sentence separators
    "。",
    "！",
    "？",
    ". ",
    "! ",
    "? ",
    "；",
    "; ",
]


def get_adaptive_chunk_params(text: str) -> tuple[int, int]:
    """Adaptively adjust chunk size and overlap based on text characteristics.

    Unified chunk size/overlap computation:
    1. Determine base chunk size from language and document length
    2. Adjust chunk size and overlap ratio by content type (dense/sparse/default)

    Args:
        text: Text content

    Returns:
        tuple[chunk_size_tokens, chunk_overlap_tokens]: Chunk size and overlap size (in tokens)
    """
    if not text:
        return 512, 51  # Default overlap ~10%

    language = detect_language(text)
    total_tokens = get_token_count(text)
    content_config = detect_content_type(text)

    # Very short text, return whole content
    if total_tokens <= 200:
        return len(text), 0

    # Base token limit by language (balancing semantic integrity and retrieval efficiency)
    if language == "chinese":
        base_token_limit = 460  # Chinese 1-2 paragraphs, ~1000-1500 chars
    elif language == "english":
        base_token_limit = 600  # English 2-3 paragraphs, ~1800-2400 chars
    else:
        base_token_limit = 540  # Mixed language compromise

    # Adjust base size by document token length
    if total_tokens <= 800:
        base_token_limit = int(base_token_limit * 0.5)
    elif total_tokens <= 2000:
        base_token_limit = int(base_token_limit * 0.7)
    elif total_tokens <= 10000:
        pass  # Use original base_token_limit
    else:
        base_token_limit = int(base_token_limit * 1.1)

    # Adjust final chunk size and overlap by content type
    chunk_size_tokens = int(base_token_limit * content_config.chunk_size_multiplier)
    chunk_overlap_tokens = int(chunk_size_tokens * content_config.overlap_ratio)

    return chunk_size_tokens, chunk_overlap_tokens


class TextChunker:
    """Text chunker (reusable instance).

    Splits long text into semantically complete chunks with Markdown structure recognition.

    Advantages:
    1. Reuses header splitter and recursive splitter, avoiding repeated creation
    2. Reuses tiktoken encoder, improving batch processing performance
    3. Stateless design, thread-safe
    """

    def __init__(self, min_chunk_tokens: int = 200, model_name: str = "gpt-4"):
        """Initialize text chunker.

        Args:
            min_chunk_tokens: Minimum chunk token count for SmartMarkdownHeaderTextSplitter
            model_name: tiktoken model name
        """
        self.min_chunk_tokens = min_chunk_tokens
        self.model_name = model_name

        # Pre-create SmartMarkdownHeaderTextSplitter (fixed config)
        self.header_splitter = SmartMarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
            ],
            min_chunk_tokens=min_chunk_tokens,
            strip_headers=False,
        )

        # RecursiveCharacter splitter needs dynamic creation per chunk_size
        # Cache to avoid re-creating splitters with same config
        self._splitter_cache: dict[tuple[int, int], RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken] = {}

    def _get_recursive_splitter(
        self, chunk_size_tokens: int, chunk_overlap_tokens: int
    ) -> RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken:
        """Get or create recursive splitter (with cache)."""
        cache_key = (chunk_size_tokens, chunk_overlap_tokens)

        if cache_key not in self._splitter_cache:
            splitter = RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken.from_tiktoken_encoder(
                chunk_size=chunk_size_tokens,
                chunk_overlap=chunk_overlap_tokens,
                separators=OPTIMIZED_SEPARATORS,
                model_name=self.model_name,
            )
            self._splitter_cache[cache_key] = splitter

        return self._splitter_cache[cache_key]

    def chunk_text(self, text: str, document_metadata: dict | None = None) -> list[Document]:
        """Chunk text into semantically complete paragraphs (Markdown format).

        Args:
            text: Text content
            document_metadata: Document metadata

        Returns:
            Chunked document list
        """
        if not text or not isinstance(text, str):
            return []

        # Compute chunk size and overlap (by language, doc length, content type)
        chunk_size_tokens, chunk_overlap_tokens = get_adaptive_chunk_params(text)

        language = detect_language(text)
        total_tokens = get_token_count(text)
        text_length = len(text)
        content_config = detect_content_type(text)
        source = (
            document_metadata.get("url", document_metadata.get("title", "unknown")) if document_metadata else "unknown"
        )
        logger.warning(
            f" Doc chunking: source={source[:60]}..., type={content_config.content_type}, "
            f"length={text_length}chars, lang={language}, total_tokens={total_tokens}, "
            f"chunk_size={chunk_size_tokens}, overlap={chunk_overlap_tokens}"
        )

        if document_metadata is None:
            document_metadata = {}
        document_metadata["original_doc_length"] = text_length
        document_metadata["content_type"] = content_config.content_type

        try:
            split_start_time = time.time()

            # Smart heading split with SmartMarkdownHeaderTextSplitter
            header_splits = self.header_splitter.split_text(text)

            # Get recursive splitter (with cache)
            text_splitter = self._get_recursive_splitter(chunk_size_tokens, chunk_overlap_tokens)

            # Unified split for each header group (built-in special block protection)
            raw_chunks = []
            for header_doc in header_splits:
                group_content = header_doc.page_content
                group_metadata = dict(header_doc.metadata)

                # Use integrated splitter (split + special block protection in one pass)
                section_splits = text_splitter.split_text(group_content)

                # Find nearest heading hierarchy before each chunk
                group_section = group_metadata.get("section", "")

                # Cumulative position: locate each split within group_content
                current_pos = 0
                for split_content in section_splits:
                    # Find split position within group_content
                    split_pos = group_content.find(split_content, current_pos)
                    if split_pos == -1:
                        split_pos = current_pos

                    # Extract headings before this split
                    headers_before = _extract_headers_before_content(group_content, split_pos)

                    # Build complete section
                    if headers_before:
                        header_path = " > ".join([title for _, title in headers_before])
                        if group_section:
                            complete_section = f"{group_section} > {header_path}"
                        else:
                            complete_section = header_path
                    else:
                        complete_section = group_section

                    split_metadata = dict(group_metadata)
                    split_metadata["section"] = complete_section
                    raw_chunks.append(Document(page_content=split_content, metadata=split_metadata))

                    current_pos = split_pos + len(split_content)

            split_elapsed = time.time() - split_start_time
            logger.warning(f"Text splitting done: {len(raw_chunks)} raw chunks, elapsed: {split_elapsed * 1000:.2f}ms")

            context_start_time = time.time()
            final_chunks = inject_structured_context(raw_chunks, document_metadata or {})
            context_elapsed = time.time() - context_start_time

            if final_chunks:
                avg_size = sum(len(c.page_content) for c in final_chunks) / len(final_chunks)
                utilization = (len(final_chunks) * avg_size / text_length * 100) if text_length > 0 else 0
                logger.warning(
                    f"  Chunking done: {len(final_chunks)} chunks, avg {avg_size:.0f} chars, "
                    f"utilization={utilization:.1f}%, elapsed: {context_elapsed * 1000:.2f}ms"
                )
            else:
                logger.warning(f"  Chunking done: 0 chunks, elapsed: {context_elapsed * 1000:.2f}ms")

            return final_chunks

        except Exception as e:
            logger.error(
                f" Text splitting failed ({type(e).__name__}: {e!s}), "
                f"source={source[:60]}..., text_length={text_length} chars, "
                f"using safe fallback: returning whole text"
            )
            # Return whole text directly, no complex fallback logic
            return [Document(page_content=text, metadata=document_metadata or {})]
