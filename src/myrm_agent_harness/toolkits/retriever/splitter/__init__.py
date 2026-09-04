"""Document chunking strategies for the retrieval pipeline.

[INPUT]
- .chunk_processor::detect_content_type, inject_structured_context (POS: chunk processing utilities)
- .recursive_character_protect_special_splitter::RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken (POS: token-aware splitter with special-block protection)
- .smart_markdown_header_text_splitter::SmartMarkdownHeaderTextSplitter (POS: Markdown header-aware splitter)
- .splitter::TextChunker (POS: high-level splitter facade)

[OUTPUT]
- RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken, SmartMarkdownHeaderTextSplitter, TextChunker, detect_content_type, inject_structured_context

[POS]
Retriever Splitter 文档切分模块入口。导出针对 Markdown、代码块、以及 Token 窗口保护的文本切分器。
"""

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
from myrm_agent_harness.toolkits.retriever.splitter.splitter import TextChunker

__all__ = [
    "RecursiveCharacterAndProtectSpecialChunkTextSplitterByTiktoken",
    "SmartMarkdownHeaderTextSplitter",
    "TextChunker",
    "detect_content_type",
    "inject_structured_context",
]
