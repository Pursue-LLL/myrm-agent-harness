"""Chunk processing utilities.

Provides content quality assessment, deduplication, context injection, and content type detection

[INPUT]
- (none)

[OUTPUT]
- ContentTypeConfig: Content type configuration.
- calculate_text_metrics: Compute text statistics (reused by multiple functions).
- detect_content_type: Detect content type and return configuration.
- assess_content_quality: Assess content quality level.
- generate_content_hash: Generate content hash for deduplication.

[POS]
Chunk processing utilities.
"""

import hashlib
import logging
import re
from dataclasses import dataclass

from langchain_core.documents import Document

from myrm_agent_harness.utils.document_utils import enhance_document_content

logger = logging.getLogger(__name__)


@dataclass
class ContentTypeConfig:
    """Content type configuration."""

    content_type: str
    chunk_size_multiplier: float
    overlap_ratio: float
    description: str


# Content type configuration (3 core types)
CONTENT_TYPE_CONFIGS = {
    "dense": ContentTypeConfig(
        content_type="dense",
        chunk_size_multiplier=1.2,
        overlap_ratio=0.15,
        description="content-dense",
    ),
    "sparse": ContentTypeConfig(
        content_type="sparse",
        chunk_size_multiplier=1.5,
        overlap_ratio=0.05,
        description="structurally-sparse",
    ),
    "default": ContentTypeConfig(
        content_type="default",
        chunk_size_multiplier=1.0,
        overlap_ratio=0.10,
        description="default",
    ),
}


def calculate_text_metrics(text: str) -> dict:
    """Compute text statistics (reused by multiple functions).

    Args:
        text: Text content (Markdown format)

    Returns:
        dict: Statistical metrics
    """
    if not text:
        return {
            "length": 0,
            "h2_count": 0,
            "sentence_count": 0,
            "avg_section_length": 0,
            "sentence_density": 0,
        }

    text_length = len(text)
    h2_count = len(re.findall(r"^##\s+.+$", text, re.MULTILINE))
    sentence_count = len(re.findall(r"[.!?。！？;；]", text))

    avg_section_length = text_length / max(h2_count, 1) if h2_count > 0 else text_length
    sentence_density = sentence_count / max(text_length, 1) * 1000

    return {
        "length": text_length,
        "h2_count": h2_count,
        "sentence_count": sentence_count,
        "avg_section_length": avg_section_length,
        "sentence_density": sentence_density,
    }


def detect_content_type(text: str) -> ContentTypeConfig:
    """Detect content type and return configuration.

    Based on sentence density, heading density, section length, etc.

    Args:
        text: Text content (Markdown format)

    Returns:
        ContentTypeConfig: Content type configuration (dense/sparse/default)
    """
    if not text:
        return CONTENT_TYPE_CONFIGS["default"]

    metrics = calculate_text_metrics(text)
    text_length = metrics["length"]
    h2_count = metrics["h2_count"]
    avg_section_length = metrics["avg_section_length"]
    sentence_density = metrics["sentence_density"]

    # sparse: high heading density + short sections (pricing tables, API lists, etc.)
    # Condition 1: very short sections, clearly a list
    if h2_count >= 8 and (
        avg_section_length < 200
        or (h2_count >= 15 and avg_section_length < 500)
        or (avg_section_length < 400 and sentence_density < 5)
    ):
        return CONTENT_TYPE_CONFIGS["sparse"]

    # dense: high sentence density and document/section long enough
    if h2_count >= 2 and ((sentence_density >= 10 and text_length >= 300) or avg_section_length > 400):
        return CONTENT_TYPE_CONFIGS["dense"]

    return CONTENT_TYPE_CONFIGS["default"]


def assess_content_quality(content: str) -> str:
    """Assess content quality level.

    Args:
        content: Document content

    Returns:
        Quality level: 'high' or 'low'
    """
    if not content or not isinstance(content, str):
        return "low"

    content_stripped = content.strip()
    if len(content_stripped) < 30:
        return "low"

    # Filter obvious junk content and navigation elements
    junk_patterns = [
        r"^(View|Click|More|Details|Expand|Collapse|Login|Register|Search|Menu|Navigation)$",
        r"^(View|Click|More|Details|Expand|Collapse|Login|Register|Search|Menu|Navigation)$",
        r"^\w+\s*>\s*\w+\s*>\s*\w+$",
        r"^\*{3,}$",
        r"^#{1,6}\s*$",
    ]

    for pattern in junk_patterns:
        if re.match(pattern, content_stripped, re.IGNORECASE):
            return "low"

    # Detect pure navigation link content (very strict conditions)
    lines = content_stripped.split("\n")
    if len(lines) >= 3:
        link_lines = sum(1 for line in lines if re.search(r"\[.+?\]\(.+?\)", line.strip()))
        # Only classify as navigation menu when almost all links (>90%) and very short
        if link_lines / len(lines) > 0.9 and len(content_stripped) < 100:
            return "low"

    metrics = calculate_text_metrics(content_stripped)
    sentence_count = metrics["sentence_count"]
    content_length = metrics["length"]

    # Additional structured content metrics
    code_blocks = len(re.findall(r"```", content_stripped)) // 2
    list_items = len(re.findall(r"^\s*[-*+•]\s+", content_stripped, re.MULTILINE))
    numbered_items = len(re.findall(r"^\s*\d+\.\s+", content_stripped, re.MULTILINE))

    # Simplified quality scoring
    density_score = 0

    # Length score (lowered threshold, 50-80 char descriptive content has value)
    if content_length >= 150:
        density_score += 3
    elif content_length >= 60:
        density_score += 2
    elif content_length >= 30:
        density_score += 1

    # Sentence score (higher weight, sentences are key quality indicator)
    if sentence_count >= 4:
        density_score += 3
    elif sentence_count >= 2:
        density_score += 2
    elif sentence_count >= 1:
        density_score += 1

    # Structure score (lists, code blocks are also valuable content)
    structure_items = code_blocks + list_items + numbered_items
    if structure_items >= 3:
        density_score += 2
    elif structure_items >= 1:
        density_score += 1

    # Lowered threshold: basic content (length + sentences or structure) qualifies as high quality
    return "high" if density_score >= 3 else "low"


def generate_content_hash(content: str) -> str:
    """Generate content hash for deduplication.

    Args:
        content: Document content

    Returns:
        8-character MD5 hash
    """
    if not content or not isinstance(content, str):
        return ""

    content_stripped = content.strip()
    if not content_stripped:
        return ""

    normalized = re.sub(r"\s+", " ", content_stripped.lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:8]


def inject_structured_context(chunks: list[Document], document_metadata: dict) -> list[Document]:
    """Inject structured context into chunks.

    Args:
        chunks: Raw chunk list
        document_metadata: Document metadata (title, url, etc.)

    Returns:
        Chunks with injected context (each chunk metadata includes chunk_index)
    """
    enriched_chunks = []
    content_hashes: set[str] = set()

    original_count = len(chunks)
    low_quality_count = 0
    duplicate_count = 0

    for chunk_index, chunk in enumerate(chunks):
        # Assess content quality
        quality = assess_content_quality(chunk.page_content)

        if quality == "low":
            low_quality_count += 1
            logger.warning(f"Skipping low-quality content, no chunk generated:\n{chunk.page_content}\n")
            continue

        # Content deduplication check
        content_hash = generate_content_hash(chunk.page_content)
        if not content_hash or content_hash in content_hashes:
            duplicate_count += 1
            continue

        content_hashes.add(content_hash)

        # Use section generated by SmartMarkdownHeaderTextSplitter directly
        section_path = chunk.metadata.get("section", "")

        # Build rich-context text
        temp_doc = Document(page_content=chunk.page_content, metadata=document_metadata)
        enriched_content = enhance_document_content(temp_doc, section_path)

        # Merge metadata
        new_metadata = dict(document_metadata)
        new_metadata.update(chunk.metadata)
        if section_path:
            new_metadata["section"] = section_path
        new_metadata["content_quality"] = quality
        new_metadata["chunk_index"] = chunk_index  # Add chunk index for adjacency detection during merging

        enriched_chunks.append(Document(page_content=enriched_content, metadata=new_metadata))

    # Log statistics
    final_count = len(enriched_chunks)
    retention_rate = f"{final_count / original_count:.1%}" if original_count > 0 else "N/A"
    logger.warning(
        f"Chunk processing done: original={original_count}, "
        f"low_quality_filtered={low_quality_count}, "
        f"deduped={duplicate_count}, "
        f"final={final_count} (retention={retention_rate})"
    )

    return enriched_chunks
