"""LangChain tool factory for Agent consumers of the code graph.

Provides two EXTENDED-layer tools: `code_graph_query` for structural queries
and `code_graph_build` for graph construction/updates.

[INPUT]
- Path (POS: workspace root)
- Path (POS: MYRM_DATA_DIR)

[OUTPUT]
- create_code_graph_tools(): factory returning [code_graph_query, code_graph_build]

[POS]
Agent adapter layer — translates LLM tool calls into CodeGraphStore,
CodeGraphAnalyzer, FlowAnalyzer, and CodeGraphSearcher operations.
EXTENDED tool layer: not loaded by default, user opts in via agent config.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.code_graph.analysis import CodeGraphAnalyzer
from myrm_agent_harness.toolkits.code_graph.builder import CodeGraphBuilder
from myrm_agent_harness.toolkits.code_graph.flows import FlowAnalyzer
from myrm_agent_harness.toolkits.code_graph.lifecycle import CodeGraphLifecycle
from myrm_agent_harness.toolkits.code_graph.search import CodeGraphSearcher, SearchMode
from myrm_agent_harness.toolkits.code_graph.store import CodeGraphStore

logger = logging.getLogger(__name__)


def create_code_graph_tools(
    workspace_root: Path,
    data_dir: Path,
) -> list[BaseTool]:
    """Create code graph tools bound to a specific workspace.

    Returns two tools:
    - code_graph_query: unified query entry for all graph operations
    - code_graph_build: build or incrementally update the code graph
    """
    lifecycle = CodeGraphLifecycle(data_dir)

    @tool("code_graph_query")
    def code_graph_query(
        operation: str,
        target: str = "",
        max_results: int = 20,
        max_depth: int = 5,
        kind_filter: str = "",
        file_filter: str = "",
    ) -> str:
        """Query the code knowledge graph for structural code information.

        Args:
            operation: One of: impact_radius, callers, dependencies,
                      structure_search, execution_flows, hotspots, stats
            target: Qualified name or search query (required for most operations)
            max_results: Maximum results to return (default 20)
            max_depth: Maximum traversal depth for impact/flow (default 5)
            kind_filter: Filter by node kind (Function, Class, Method, etc.)
            file_filter: Filter by file path substring

        Operations:
        - impact_radius: Find all code affected by changes to target
        - callers: Find who calls the target
        - dependencies: Find what target depends on
        - structure_search: Search code symbols by name/path
        - execution_flows: Detect entry points or trace flow from target
        - hotspots: Find hub/bridge nodes (high-impact code)
        - stats: Get graph statistics
        """
        info = lifecycle.get_workspace_info(str(workspace_root))
        if not info.exists:
            return json.dumps({
                "error": "Code graph not built yet. Run code_graph_build first.",
            })

        store = lifecycle.open_store(str(workspace_root))
        try:
            return _execute_query(
                store, operation, target, max_results, max_depth,
                kind_filter, file_filter,
            )
        finally:
            store.close()

    @tool("code_graph_build")
    def code_graph_build(mode: str = "incremental") -> str:
        """Build or update the code knowledge graph for the current workspace.

        Args:
            mode: "full" for complete rebuild, "incremental" for git-diff update

        Parses source files using Tree-sitter AST analysis and populates the
        graph with functions, classes, imports, calls, and inheritance relationships.
        """
        store = lifecycle.open_store(str(workspace_root))
        try:
            builder = CodeGraphBuilder(store, workspace_root)
            if mode == "full":
                result = builder.build_full()
            else:
                result = builder.build_incremental()

            return json.dumps({
                "status": "success",
                "mode": mode,
                "files_processed": result.files_processed,
                "files_skipped": result.files_skipped,
                "files_failed": result.files_failed,
                "nodes_added": result.nodes_added,
                "edges_added": result.edges_added,
                "elapsed_seconds": round(result.elapsed_seconds, 2),
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        finally:
            store.close()

    return [code_graph_query, code_graph_build]


def _execute_query(
    store: CodeGraphStore,
    operation: str,
    target: str,
    max_results: int,
    max_depth: int,
    kind_filter: str,
    file_filter: str,
) -> str:

    if operation == "stats":
        stats = store.get_stats()
        return json.dumps(stats)

    if operation == "impact_radius":
        if not target:
            return json.dumps({"error": "target required for impact_radius"})
        result = CodeGraphAnalyzer(store).impact_radius(
            target, max_depth=max_depth, max_nodes=max_results,
        )
        return json.dumps({
            "target": result.target,
            "affected_count": len(result.affected_nodes),
            "affected_files": result.affected_files,
            "depth_reached": result.depth_reached,
            "affected_nodes": result.affected_nodes[:max_results],
        })

    if operation == "callers":
        if not target:
            return json.dumps({"error": "target required for callers"})
        rows = store.find_callers(target, max_results=max_results)
        return json.dumps({"target": target, "callers": rows})

    if operation == "dependencies":
        if not target:
            return json.dumps({"error": "target required for dependencies"})
        rows = store.find_dependencies(target, max_results=max_results)
        return json.dumps({"target": target, "dependencies": rows})

    if operation == "structure_search":
        if not target:
            return json.dumps({"error": "query required for structure_search"})
        searcher = CodeGraphSearcher(store)
        response = searcher.search(
            target,
            max_results=max_results,
            kind_filter=kind_filter or None,
            file_filter=file_filter or None,
            mode=SearchMode.FTS,
        )
        return json.dumps({
            "query": response.query,
            "results": [
                {
                    "qualified_name": r.qualified_name,
                    "name": r.name,
                    "kind": r.kind,
                    "file_path": r.file_path,
                    "line_start": r.line_start,
                    "score": r.score,
                }
                for r in response.results
            ],
            "total_candidates": response.total_candidates,
        })

    if operation == "execution_flows":
        flow_analyzer = FlowAnalyzer(store)
        if target:
            trace = flow_analyzer.trace_flow(
                target, max_depth=max_depth, max_nodes=max_results,
            )
            return json.dumps({
                "entry_point": trace.entry_point,
                "steps": [
                    {
                        "qualified_name": s.qualified_name,
                        "file_path": s.file_path,
                        "kind": s.kind,
                        "depth": s.depth,
                        "edge_type": s.edge_type,
                    }
                    for s in trace.steps
                ],
                "depth_reached": trace.depth_reached,
                "files_touched": trace.files_touched,
            })
        entry_points = flow_analyzer.detect_entry_points(max_results=max_results)
        return json.dumps({
            "entry_points": [
                {
                    "qualified_name": ep.qualified_name,
                    "file_path": ep.file_path,
                    "name": ep.name,
                    "entry_type": ep.entry_type,
                    "line": ep.line,
                }
                for ep in entry_points
            ],
        })

    if operation == "hotspots":
        result = CodeGraphAnalyzer(store).detect_hotspots(top_k=max_results)
        return json.dumps({
            "total_nodes": result.total_nodes,
            "total_edges": result.total_edges,
            "hotspots": [
                {
                    "qualified_name": h.qualified_name,
                    "file_path": h.file_path,
                    "kind": h.kind,
                    "in_degree": h.in_degree,
                    "out_degree": h.out_degree,
                    "betweenness": h.betweenness,
                    "is_hub": h.is_hub,
                    "is_bridge": h.is_bridge,
                }
                for h in result.hotspots
            ],
        })

    return json.dumps({"error": f"Unknown operation: {operation}"})
