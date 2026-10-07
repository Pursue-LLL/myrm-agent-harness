"""Virtual page swap manager for managing tiered code context memory.

Enforces a constant token budget (e.g., ≤4000 tokens) across multi-file operations
using OS-inspired virtual paging: active pages reside in core memory, while inactive
pages are swapped out to archival cache with symbol stubs retained for page-fault resolution.
"""

from __future__ import annotations

import math

from .ast_symbol_stub_extractor import AstSymbolStubExtractor
from .code_context_pager import CodeContextPager
from .virtual_paged_code_types import (
    CodeSymbolStub,
    PageFaultEvent,
    PageLifecycleState,
    PageSwapAudit,
    VirtualCodePage,
)


class VirtualPageSwapManager:
    """Manages virtual code pages with LRU page-out and symbol-driven page-in."""

    def __init__(
        self,
        max_core_tokens: int = 4000,
        pager: CodeContextPager | None = None,
        stub_extractor: AstSymbolStubExtractor | None = None,
    ) -> None:
        self._max_core_tokens = max(1, max_core_tokens)
        self._stub_extractor = stub_extractor or AstSymbolStubExtractor()
        self._pager = pager or CodeContextPager(stub_extractor=self._stub_extractor)

        self._pages: dict[str, VirtualCodePage] = {}
        self._file_page_ids: dict[str, list[str]] = {}
        self._file_stubs: dict[str, tuple[CodeSymbolStub, ...]] = {}
        self._symbol_to_page: dict[str, str] = {}

        self._tick: int = 0
        self._total_page_faults: int = 0
        self._total_swapped_out_pages: int = 0
        self._token_history: list[int] = []

    @property
    def max_core_tokens(self) -> int:
        """Maximum active core token budget."""
        return self._max_core_tokens

    def load_file(
        self,
        file_path: str,
        code_content: str,
    ) -> tuple[VirtualCodePage, ...]:
        """Paginates and registers a source file into the virtual paging system."""
        pages = self._pager.paginate_file(file_path, code_content)
        if not pages:
            return ()

        all_file_stubs = self._stub_extractor.extract_stubs(file_path, code_content)
        self._file_stubs[file_path] = all_file_stubs

        page_ids: list[str] = []
        for page in pages:
            self._tick += 1
            registered_page = VirtualCodePage(
                page_id=page.page_id,
                file_path=page.file_path,
                content=page.content,
                ast_symbols=page.ast_symbols,
                token_count=page.token_count,
                is_dirty=page.is_dirty,
                lifecycle_state=PageLifecycleState.CORE_RESIDENT,
                last_accessed_tick=self._tick,
                metadata=dict(page.metadata),
            )
            self._pages[registered_page.page_id] = registered_page
            page_ids.append(registered_page.page_id)

            for sym in registered_page.ast_symbols:
                self._symbol_to_page[sym.symbol_name] = registered_page.page_id

        self._file_page_ids[file_path] = page_ids
        self._enforce_budget()
        return tuple(self._pages[pid] for pid in page_ids)

    def touch_page(self, page_id: str) -> bool:
        """Marks a page as accessed, swapping it back into core memory if archived."""
        if page_id not in self._pages:
            return False

        self._tick += 1
        page = self._pages[page_id]

        if page.lifecycle_state == PageLifecycleState.ARCHIVED_PAGE:
            self._total_page_faults += 1
            swapped_in = VirtualCodePage(
                page_id=page.page_id,
                file_path=page.file_path,
                content=page.content,
                ast_symbols=page.ast_symbols,
                token_count=page.token_count,
                is_dirty=page.is_dirty,
                lifecycle_state=PageLifecycleState.CORE_RESIDENT,
                last_accessed_tick=self._tick,
                metadata=dict(page.metadata),
            )
            self._pages[page_id] = swapped_in
            self._enforce_budget()
            return True

        updated = VirtualCodePage(
            page_id=page.page_id,
            file_path=page.file_path,
            content=page.content,
            ast_symbols=page.ast_symbols,
            token_count=page.token_count,
            is_dirty=page.is_dirty,
            lifecycle_state=page.lifecycle_state,
            last_accessed_tick=self._tick,
            metadata=dict(page.metadata),
        )
        self._pages[page_id] = updated
        return True

    def resolve_symbol(self, symbol_name: str) -> PageFaultEvent:
        """Resolves a symbol reference, triggering a page-fault swap-in if archived."""
        page_id = self._symbol_to_page.get(symbol_name)
        if not page_id or page_id not in self._pages:
            return PageFaultEvent(
                page_id="",
                file_path="",
                requested_symbol=symbol_name,
                resolved=False,
                reason=f"Symbol '{symbol_name}' not registered in virtual paging index",
            )

        target_page = self._pages[page_id]
        if target_page.lifecycle_state == PageLifecycleState.CORE_RESIDENT:
            self.touch_page(page_id)
            return PageFaultEvent(
                page_id=page_id,
                file_path=target_page.file_path,
                requested_symbol=symbol_name,
                resolved=True,
                reason="Symbol page is already resident in core context",
            )

        # Trigger page fault swap-in
        self.touch_page(page_id)
        return PageFaultEvent(
            page_id=page_id,
            file_path=target_page.file_path,
            requested_symbol=symbol_name,
            resolved=True,
            reason="Page fault resolved: archived page swapped into core context",
        )

    def render_active_context(self) -> str:
        """Renders the combined context of core-resident pages and archived symbol stubs."""
        blocks: list[str] = []

        for file_path, page_ids in self._file_page_ids.items():
            resident_pages = [
                self._pages[pid]
                for pid in page_ids
                if pid in self._pages
                and self._pages[pid].lifecycle_state == PageLifecycleState.CORE_RESIDENT
            ]

            if not resident_pages:
                # All pages for this file are archived; render lightweight stub header
                stubs = self._file_stubs.get(file_path, ())
                blocks.append(self._stub_extractor.format_stubs_manifest(file_path, stubs))
            else:
                blocks.append(f"# File: {file_path}")
                for p in resident_pages:
                    idx_meta = p.metadata.get("page_index", "?")
                    lines_range = (
                        f"L{p.metadata.get('line_start')}-L{p.metadata.get('line_end')}"
                        if "line_start" in p.metadata
                        else ""
                    )
                    blocks.append(f"## Page {idx_meta} ({lines_range})")
                    blocks.append(p.content.rstrip())

                archived_count = len(page_ids) - len(resident_pages)
                if archived_count > 0:
                    blocks.append(
                        f"## Note: {archived_count} page(s) paged out to archival cache (Stubs active)"
                    )

        return "\n\n".join(blocks)

    def audit_context_stability(self) -> PageSwapAudit:
        """Calculates token stability metrics and budget adherence."""
        active_tokens = sum(
            p.token_count
            for p in self._pages.values()
            if p.lifecycle_state == PageLifecycleState.CORE_RESIDENT
        )
        resident_count = sum(
            1
            for p in self._pages.values()
            if p.lifecycle_state == PageLifecycleState.CORE_RESIDENT
        )
        archived_count = sum(
            1
            for p in self._pages.values()
            if p.lifecycle_state == PageLifecycleState.ARCHIVED_PAGE
        )

        variance_ratio = 0.0
        if self._token_history:
            # Measure steady-state stability in saturated working set phase
            steady_history = (
                [t for t in self._token_history if t >= self._max_core_tokens * 0.5]
                if self._total_swapped_out_pages > 0
                else self._token_history
            ) or self._token_history
            avg_tokens = sum(steady_history) / len(steady_history)
            variance = sum((t - avg_tokens) ** 2 for t in steady_history) / len(
                steady_history
            )
            variance_ratio = math.sqrt(variance) / self._max_core_tokens

        return PageSwapAudit(
            active_core_tokens=active_tokens,
            max_budget_tokens=self._max_core_tokens,
            resident_pages_count=resident_count,
            archived_pages_count=archived_count,
            total_page_faults=self._total_page_faults,
            total_swapped_out_pages=self._total_swapped_out_pages,
            is_budget_exceeded=active_tokens > self._max_core_tokens,
            stability_variance_ratio=round(variance_ratio, 4),
        )

    def _enforce_budget(self) -> None:
        """Evicts least recently accessed pages until active tokens <= max_core_tokens."""
        resident_pages = [
            p
            for p in self._pages.values()
            if p.lifecycle_state == PageLifecycleState.CORE_RESIDENT
        ]
        active_tokens = sum(p.token_count for p in resident_pages)

        if active_tokens <= self._max_core_tokens:
            self._token_history.append(active_tokens)
            return

        # Sort by last_accessed_tick ascending (LRU)
        resident_pages.sort(key=lambda p: p.last_accessed_tick)

        # Evict until budget satisfied, leaving at least the most recently accessed page
        for page in resident_pages[:-1]:
            if active_tokens <= self._max_core_tokens:
                break

            archived = VirtualCodePage(
                page_id=page.page_id,
                file_path=page.file_path,
                content=page.content,
                ast_symbols=page.ast_symbols,
                token_count=page.token_count,
                is_dirty=page.is_dirty,
                lifecycle_state=PageLifecycleState.ARCHIVED_PAGE,
                last_accessed_tick=page.last_accessed_tick,
                metadata=dict(page.metadata),
            )
            self._pages[page.page_id] = archived
            self._total_swapped_out_pages += 1
            active_tokens -= page.token_count

        self._token_history.append(active_tokens)
