"""Code context pager for segmenting source files into virtual memory pages.

Splits multi-thousand-line source code into discrete 2KB~4KB virtual code pages,
attaching extracted AST symbol stubs and token estimations to each page.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from .ast_symbol_stub_extractor import AstSymbolStubExtractor
from .virtual_paged_code_types import CodeSymbolStub, PageLifecycleState, VirtualCodePage


class CodeContextPager:
    """Partitions source files into standard-sized virtual code pages."""

    def __init__(
        self,
        page_size_chars: int = 2500,
        chars_per_token_ratio: float = 3.8,
        stub_extractor: AstSymbolStubExtractor | None = None,
    ) -> None:
        self._page_size = page_size_chars
        self._chars_per_token_ratio = chars_per_token_ratio
        self._stub_extractor = stub_extractor or AstSymbolStubExtractor()

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def paginate_file(
        self,
        file_path: str,
        code_content: str,
    ) -> tuple[VirtualCodePage, ...]:
        """Paginates a source file into a tuple of VirtualCodePage objects."""
        if not code_content.strip():
            return ()

        all_stubs = self._stub_extractor.extract_stubs(file_path, code_content)
        lines = code_content.splitlines(keepends=True)

        pages: list[VirtualCodePage] = []
        current_chunk: list[str] = []
        current_chars = 0
        page_idx = 1
        chunk_start_line = 1

        file_hash = hashlib.sha256(file_path.encode("utf-8")).hexdigest()[:8]

        for line_num, line in enumerate(lines, start=1):
            current_chunk.append(line)
            current_chars += len(line)

            # Reached standard page size boundary or last line
            if current_chars >= self._page_size or line_num == len(lines):
                page_text = "".join(current_chunk)
                chunk_end_line = line_num

                # Filter stubs overlapping with current page line range
                page_stubs = self._find_stubs_in_range(all_stubs, chunk_start_line, chunk_end_line)
                page_tokens = self.estimate_tokens(page_text)
                page_id = f"page_{file_hash}_{page_idx:03d}"

                pages.append(
                    VirtualCodePage(
                        page_id=page_id,
                        file_path=file_path,
                        content=page_text,
                        ast_symbols=page_stubs,
                        token_count=page_tokens,
                        is_dirty=False,
                        lifecycle_state=PageLifecycleState.CORE_RESIDENT,
                        metadata={
                            "page_index": str(page_idx),
                            "line_start": str(chunk_start_line),
                            "line_end": str(chunk_end_line),
                        },
                    )
                )

                page_idx += 1
                current_chunk = []
                current_chars = 0
                chunk_start_line = line_num + 1

        return tuple(pages)

    def _find_stubs_in_range(
        self,
        stubs: Sequence[CodeSymbolStub],
        start_line: int,
        end_line: int,
    ) -> tuple[CodeSymbolStub, ...]:
        """Filters symbol stubs starting within the page boundary."""
        matched: list[CodeSymbolStub] = []
        for s in stubs:
            if start_line <= s.line_start <= end_line:
                matched.append(s)
        return tuple(matched)
