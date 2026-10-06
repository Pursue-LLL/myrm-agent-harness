# [INPUT] CodeSymbol definitions, DependencyEdge connections, and workspace file metadata.
# [OUTPUT] In-memory indexed and persistent CodeGraphMemoryStore with incremental sync capabilities.
# [POS] myrm_agent_harness.toolkits.memory.codegraph.store

"""CodeGraph memory store maintaining symbol topology and caller inversions."""

import hashlib
import time
from collections import defaultdict

from myrm_agent_harness.toolkits.memory.codegraph.ast_parser import (
    AstTopologyExtractor,
)
from myrm_agent_harness.toolkits.memory.codegraph.types import (
    CodeGraphAsset,
    CodeSymbol,
    DependencyEdge,
    EdgeKind,
)


class CodeGraphMemoryStore:
    """Stores code symbols, dependencies, and caller indexes with incremental synchronization."""

    def __init__(self, repo_id: str = "default_workspace") -> None:
        self.repo_id = repo_id
        self._symbols_by_id: dict[str, CodeSymbol] = {}
        self._symbols_by_name: dict[str, list[CodeSymbol]] = defaultdict(list)
        self._edges: list[DependencyEdge] = []
        self._file_symbols: dict[str, set[str]] = defaultdict(set)
        self._file_mtimes: dict[str, float] = {}

        # Inverted index: callee_name -> set of caller symbol_ids
        self._callers_index: dict[str, set[str]] = defaultdict(set)

    def evict_file(self, file_path: str) -> None:
        """Remove all indexed symbols and edges belonging to a specific file."""
        symbol_ids = self._file_symbols.pop(file_path, set())
        for sym_id in symbol_ids:
            sym = self._symbols_by_id.pop(sym_id, None)
            if sym and sym.name in self._symbols_by_name:
                self._symbols_by_name[sym.name] = [
                    s for s in self._symbols_by_name[sym.name] if s.symbol_id != sym_id
                ]
                if not self._symbols_by_name[sym.name]:
                    self._symbols_by_name.pop(sym.name, None)

        # Remove edges originating from this file
        self._edges = [
            e for e in self._edges if not e.source_id.startswith(f"{file_path}::")
        ]
        self._rebuild_callers_index()
        self._file_mtimes.pop(file_path, None)

    def index_file(
        self,
        file_path: str,
        symbols: list[CodeSymbol],
        edges: list[DependencyEdge],
        mtime: float = 0.0,
    ) -> None:
        """Index a file's symbols and edges, replacing any prior entries for that file."""
        self.evict_file(file_path)

        for sym in symbols:
            self._symbols_by_id[sym.symbol_id] = sym
            self._symbols_by_name[sym.name].append(sym)
            self._file_symbols[file_path].add(sym.symbol_id)

        for edge in edges:
            self._edges.append(edge)
            if edge.edge_kind == EdgeKind.CALLS:
                self._callers_index[edge.target_id].add(edge.source_id)

        self._file_mtimes[file_path] = mtime or time.time()

    def _rebuild_callers_index(self) -> None:
        """Reconstruct callers inverted index from current edges."""
        self._callers_index.clear()
        for edge in self._edges:
            if edge.edge_kind == EdgeKind.CALLS:
                self._callers_index[edge.target_id].add(edge.source_id)

    def incremental_sync_files(
        self,
        files_data: list[tuple[str, str, float]],
        extractor: AstTopologyExtractor,
    ) -> tuple[int, int]:
        """Perform incremental synchronization for files whose mtime or content changed.

        files_data: list of (file_path, source_code, mtime).
        Returns: (indexed_files_count, total_symbols_count).
        """
        indexed_count = 0
        for file_path, source_code, mtime in files_data:
            current_mtime = self._file_mtimes.get(file_path, -1.0)
            if mtime > current_mtime or current_mtime == -1.0:
                symbols, edges = extractor.extract_from_source(source_code, file_path)
                self.index_file(file_path, symbols, edges, mtime)
                indexed_count += 1

        return indexed_count, len(self._symbols_by_id)

    def get_symbol(self, symbol_id: str) -> CodeSymbol | None:
        """Retrieve symbol metadata by exact symbol_id."""
        return self._symbols_by_id.get(symbol_id)

    def find_symbols_by_name(self, name: str) -> list[CodeSymbol]:
        """Find all symbols declared with the specified name."""
        return list(self._symbols_by_name.get(name, []))

    def get_direct_callers(self, target_name: str) -> list[str]:
        """Get all caller symbol_ids that directly call target_name."""
        return sorted(self._callers_index.get(target_name, set()))

    def list_all_symbols(self) -> list[CodeSymbol]:
        """Return list of all indexed code symbols."""
        return list(self._symbols_by_id.values())

    def get_asset_snapshot(self) -> CodeGraphAsset:
        """Generate an immutable project-level snapshot of the current CodeGraph."""
        content_repr = f"{len(self._symbols_by_id)}::{len(self._edges)}"
        version_hash = hashlib.sha256(content_repr.encode("utf-8")).hexdigest()[:16]

        return CodeGraphAsset(
            repo_id=self.repo_id,
            version_hash=version_hash,
            total_symbols=len(self._symbols_by_id),
            total_edges=len(self._edges),
            updated_at=time.time(),
            symbols=dict(self._symbols_by_id),
            edges=list(self._edges),
        )
