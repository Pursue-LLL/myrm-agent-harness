"""Smart Markdown header text splitter.

Header-aware splitter with minimum-token constraints; sections that are too small
are merged with subsequent content.

[INPUT]
langchain_core.documents::Document (POS: LangChain document container)
utils.text_utils::get_token_count (POS: Token counting utility)

[OUTPUT]
SmartMarkdownHeaderTextSplitter: Splits Markdown by headers with min-token merging

[POS]
Markdown-aware splitter. Splits documents along header boundaries while enforcing a
minimum chunk-token threshold, producing chunks with header/section metadata.

"""

import logging
import re

from langchain_core.documents import Document

from myrm_agent_harness.utils.text_utils import get_token_count

logger = logging.getLogger(__name__)


class SmartMarkdownHeaderTextSplitter:
    """Smart Markdown heading splitter.

    Features:
    1. Supports all heading levels (#/##/###/#### etc.)
    2. Minimum token limit: merges with subsequent content if below threshold
    4. Metadata headers stored as arrays (supports merging sibling headings)
    5. Metadata Section field stores parent heading path
    """

    def __init__(
        self,
        headers_to_split_on: list[tuple[str, str]],
        min_chunk_tokens: int = 200,
        strip_headers: bool = False,
    ):
        """Initialize the splitter

        Args:
            headers_to_split_on: Heading list to split on, e.g. [("#", "Header 1"), ("##", "Header 2")]
            min_chunk_tokens: Minimum chunk token count (merges if below)
            strip_headers: Whether to strip heading lines (not yet supported, kept for compatibility)
        """
        self.headers_to_split_on = sorted(headers_to_split_on, key=lambda x: len(x[0]))
        self.min_chunk_tokens = min_chunk_tokens
        self.strip_headers = strip_headers

        # Build regex
        self.header_patterns = {}
        for marker, name in headers_to_split_on:
            escaped = re.escape(marker)
            pattern = re.compile(rf"^{escaped}\s+(.+?)$", re.MULTILINE)
            self.header_patterns[name] = pattern

    def split_text(self, text: str) -> list[Document]:
        """Split text and return Document list.

        Args:
            text: Markdown text

        Returns:
            Document list with Header arrays and Section paths in metadata
        """
        # Step 1: Extract all heading positions and content
        headers = self._extract_headers(text)

        if not headers:
            # No headings, return as single block
            doc = Document(page_content=text, metadata={})
            return [doc]

        # Step 2: Split text by heading positions
        sections = self._split_by_headers(text, headers)

        # Step 3: Merge sections smaller than min_chunk_tokens
        merged_sections = self._merge_small_sections(sections)

        # Step 4: Build Document list
        documents = []
        for section in merged_sections:
            doc = Document(page_content=section["content"], metadata=section["metadata"])
            documents.append(doc)

        return documents

    def _extract_headers(self, text: str) -> list[dict]:
        """Extract all heading positions, levels, and content (excluding # in code blocks).

        Returns:
            [{"pos": position, "level": level_name, "title": heading_text}, ...]
        """
        # Find all code block ranges first
        code_block_ranges = []
        code_pattern = re.compile(r"```[\s\S]*?```", re.MULTILINE)
        for match in code_pattern.finditer(text):
            code_block_ranges.append((match.start(), match.end()))

        headers = []

        for level_name, pattern in self.header_patterns.items():
            for match in pattern.finditer(text):
                pos = match.start()

                # Check if inside a code block
                in_code_block = any(start <= pos < end for start, end in code_block_ranges)
                if in_code_block:
                    continue

                headers.append(
                    {
                        "pos": pos,
                        "level": level_name,
                        "title": match.group(1).strip(),
                        "full_line": match.group(0),
                    }
                )

        # Sort by position
        headers.sort(key=lambda x: x["pos"])
        return headers

    def _split_by_headers(self, text: str, headers: list[dict]) -> list[dict]:
        """Split text by heading positions, building section list.

        Note: each section contains complete "heading+content", headings are not separated from content.

        Returns:
            [{"content": content, "headers": header_stack, "parent_headers": parent_headers}, ...]
        """
        sections = []

        header_stack = {}

        # If there is content before the first heading, make it the first section
        if headers and headers[0]["pos"] > 0:
            prefix_content = text[: headers[0]["pos"]]
            sections.append(
                {
                    "content": prefix_content,
                    "headers": {},
                    "parent_headers": {},
                }
            )

        for i, header in enumerate(headers):
            self._update_header_stack(header_stack, header)

            # Extract section content: from current heading to just before next heading
            start_pos = header["pos"]
            if i < len(headers) - 1:
                end_pos = headers[i + 1]["pos"]
            else:
                end_pos = len(text)

            content = text[start_pos:end_pos]

            section = {
                "content": content,
                "headers": dict(header_stack),
                "parent_headers": self._get_parent_headers(header_stack, header["level"]),
            }
            sections.append(section)

        return sections

    def _update_header_stack(self, stack: dict, header: dict):
        """Update header stack: clear current and lower levels, add new heading."""
        current_level = header["level"]

        # Clear current and lower levels
        # Assumes Header 1 > Header 2 > Header 3 > Header 4
        levels_order = [name for _, name in self.headers_to_split_on]
        current_idx = levels_order.index(current_level)

        for level in list(stack.keys()):
            if levels_order.index(level) >= current_idx:
                del stack[level]

        # Add new heading
        stack[current_level] = header["title"]

    def _get_parent_headers(self, stack: dict, current_level: str) -> dict:
        """Get parent headings of the current level."""
        levels_order = [name for _, name in self.headers_to_split_on]
        current_idx = levels_order.index(current_level)

        parent = {}
        for level, title in stack.items():
            if levels_order.index(level) < current_idx:
                parent[level] = title

        return parent

    def _merge_small_sections(self, sections: list[dict]) -> list[dict]:
        """Merge sections smaller than min_chunk_tokens.

        Strategy:
        1. Accumulate until >= min_chunk_tokens, then emit as block
        2. < min_chunk_tokens: keep accumulating (merge with next)
        3. Final small buffer: try merging into previous block (if not too large)
        """
        merged = []
        buffer_sections = []
        buffer_tokens = 0

        for section in sections:
            section_tokens = get_token_count(section["content"])
            buffer_sections.append(section)
            buffer_tokens += section_tokens

            if buffer_tokens >= self.min_chunk_tokens:
                merged.append(self._combine_sections(buffer_sections))
                buffer_sections = []
                buffer_tokens = 0

        # Handle final buffer
        if buffer_sections:
            # If final buffer is small (< min_chunk_tokens/2) and previous block exists, try merging
            if merged and buffer_tokens < self.min_chunk_tokens / 2:
                # Get previous block sections (simplified: append content directly)
                last_merged = merged[-1]
                last_content = last_merged["content"]
                last_tokens = get_token_count(last_content)

                # If merged result is not too large (< 1.5x min_chunk_tokens), merge
                if last_tokens + buffer_tokens < self.min_chunk_tokens * 1.5:
                    buffer_content = "".join(s["content"] for s in buffer_sections)
                    last_merged["content"] = last_content + buffer_content
                    # Update metadata (simplified, keep existing metadata)
                else:
                    # Too large, make separate block
                    merged.append(self._combine_sections(buffer_sections))
            else:
                # Buffer not small enough or no previous block, make separate block
                merged.append(self._combine_sections(buffer_sections))

        return merged

    def _combine_sections(self, sections: list[dict]) -> dict:
        """Merge multiple sections into one.

        Returns:
            {"content": merged_content, "metadata": merged_metadata}
        """
        if not sections:
            return {"content": "", "metadata": {}}

        if len(sections) == 1:
            # Single section, build metadata directly
            return {"content": sections[0]["content"], "metadata": self._build_metadata(sections[0])}

        # Merge multiple sections
        combined_content = "".join(s["content"] for s in sections)

        # Merge metadata: headers become arrays
        combined_headers = {}
        for section in sections:
            for level, title in section["headers"].items():
                if level not in combined_headers:
                    combined_headers[level] = []
                if title not in combined_headers[level]:
                    combined_headers[level].append(title)

        metadata = {}
        for level, titles in combined_headers.items():
            metadata[level] = titles[0]
            metadata[f"{level}s"] = titles

        # Build section (keep parents only, detect headings in content)
        metadata["section"] = self._build_section_for_chunk(combined_content, combined_headers)

        return {"content": combined_content, "metadata": metadata}

    def _build_metadata(self, section: dict) -> dict:
        """Build metadata for a single section."""
        metadata = {}

        # Add current section headers
        for level, title in section["headers"].items():
            metadata[level] = title
            metadata[f"{level}s"] = [title]  # Array form

        # Build section
        combined_headers = {level: [title] for level, title in section["headers"].items()}
        metadata["section"] = self._build_section_for_chunk(section["content"], combined_headers)

        return metadata

    def _build_section_for_chunk(self, content: str, combined_headers: dict) -> str:
        """Build section path: include only parent headings, exclude deepest heading of current chunk.

        Strategy:
        1. Find first level with multiple headings (e.g. Header 3: ['Section B', 'Section C'])
        2. Section includes all headings before that level
        3. If no multi-value level, exclude the first heading at content start

        Args:
            content: Chunk content
            combined_headers: {level_name: [titles]}

        Returns:
            Section path string (hierarchical: level1 > level2 > level3)
        """
        all_levels = [(level, titles) for level, titles in combined_headers.items()]

        if not all_levels:
            return ""

        # Find first level with multiple headings
        multi_value_level_index = None
        for i, (_, titles) in enumerate(all_levels):
            if len(titles) > 1:
                multi_value_level_index = i
                break

        # Build section path
        headers = []

        if multi_value_level_index is not None:
            # Multi-value level found, include all headings before that level
            for i, (_, titles) in enumerate(all_levels):
                if i >= multi_value_level_index:
                    break
                headers.append(titles[0])
        else:
            # No multi-value level, exclude first heading at content start
            first_header_in_content = None
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("#"):
                    first_header_in_content = line.lstrip("#").strip()
                    break

            for _, titles in all_levels:
                title = titles[0]
                if title == first_header_in_content:
                    break
                headers.append(title)

        return " > ".join(headers)
