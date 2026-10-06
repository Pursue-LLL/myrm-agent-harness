# [INPUT] CodeGraphMemoryStore, AstTopologyExtractor, and CodeImpactAnalyzer.
# [OUTPUT] Unit tests verifying symbol parsing, incremental indexing, and impact analysis blast radius.
# [POS] tests.toolkits.memory.test_codegraph_memory_engine

"""Unit tests for CodeGraph memory asset and impact analysis engine."""

import pytest

from myrm_agent_harness.toolkits.memory.codegraph.ast_parser import (
    AstTopologyExtractor,
)
from myrm_agent_harness.toolkits.memory.codegraph.impact_analyzer import (
    CodeImpactAnalyzer,
)
from myrm_agent_harness.toolkits.memory.codegraph.store import (
    CodeGraphMemoryStore,
)
from myrm_agent_harness.toolkits.memory.codegraph.tool import (
    CodeImpactAnalysisTool,
)
from myrm_agent_harness.toolkits.memory.codegraph.types import (
    EdgeKind,
    ImpactRiskLevel,
    SymbolKind,
)


@pytest.fixture
def extractor() -> AstTopologyExtractor:
    return AstTopologyExtractor()


@pytest.fixture
def sample_code_module_a() -> str:
    return '''
class BaseService:
    def execute(self) -> bool:
        return True

class DataProcessor(BaseService):
    def process_data(self, item: str) -> bool:
        return self.execute()

def helper_calculate(x: int) -> int:
    return x * 2
'''


@pytest.fixture
def sample_code_module_b() -> str:
    return '''
from module_a import helper_calculate, DataProcessor

def compute_metrics(val: int) -> int:
    res = helper_calculate(val)
    return res

def run_pipeline() -> None:
    compute_metrics(10)
'''


def test_ast_topology_extractor_single_file(
    extractor: AstTopologyExtractor, sample_code_module_a: str
) -> None:
    """Verify that class, methods, functions, and inheritance edges are extracted."""
    symbols, edges = extractor.extract_from_source(
        sample_code_module_a, "services/module_a.py"
    )

    names = {s.name: s for s in symbols}
    assert "BaseService" in names
    assert names["BaseService"].kind == SymbolKind.CLASS
    assert "process_data" in names
    assert names["process_data"].kind == SymbolKind.METHOD
    assert "helper_calculate" in names
    assert names["helper_calculate"].kind == SymbolKind.FUNCTION
    assert names["helper_calculate"].parameters == ["x"]

    # Verify inheritance edge
    inherits_edges = [e for e in edges if e.edge_kind == EdgeKind.INHERITS]
    assert len(inherits_edges) == 1
    assert inherits_edges[0].source_id == "services/module_a.py::DataProcessor"
    assert inherits_edges[0].target_id == "BaseService"


def test_ast_topology_extractor_syntax_error_resilience(
    extractor: AstTopologyExtractor,
) -> None:
    """Verify that broken Python files gracefully degrade to empty symbols."""
    broken_code = "def invalid_syntax( \n  broken!!"
    symbols, edges = extractor.extract_from_source(broken_code, "broken.py")
    assert symbols == []
    assert edges == []


def test_codegraph_memory_store_indexing_and_eviction(
    extractor: AstTopologyExtractor, sample_code_module_a: str
) -> None:
    """Verify file indexing, caller inversion, and clean eviction."""
    store = CodeGraphMemoryStore(repo_id="test_repo")
    symbols, edges = extractor.extract_from_source(
        sample_code_module_a, "module_a.py"
    )

    store.index_file("module_a.py", symbols, edges, mtime=100.0)
    assert len(store.list_all_symbols()) == 5
    assert store.get_symbol("module_a.py::helper_calculate") is not None

    # Evict file
    store.evict_file("module_a.py")
    assert len(store.list_all_symbols()) == 0
    assert store.get_symbol("module_a.py::helper_calculate") is None


def test_codegraph_incremental_sync(
    extractor: AstTopologyExtractor, sample_code_module_a: str
) -> None:
    """Verify incremental sync only parses updated files."""
    store = CodeGraphMemoryStore(repo_id="test_repo")
    files_data = [("module_a.py", sample_code_module_a, 100.0)]

    indexed_count, total = store.incremental_sync_files(files_data, extractor)
    assert indexed_count == 1
    assert total == 5

    # Second sync with same mtime should do nothing
    indexed_count_2, total_2 = store.incremental_sync_files(files_data, extractor)
    assert indexed_count_2 == 0
    assert total_2 == 5

    # Sync with newer mtime
    newer_files = [("module_a.py", sample_code_module_a, 105.0)]
    indexed_count_3, _ = store.incremental_sync_files(newer_files, extractor)
    assert indexed_count_3 == 1


def test_impact_analyzer_multi_hop_blast_radius(
    extractor: AstTopologyExtractor,
    sample_code_module_a: str,
    sample_code_module_b: str,
) -> None:
    """Verify multi-hop callers: helper_calculate -> compute_metrics -> run_pipeline."""
    store = CodeGraphMemoryStore(repo_id="test_repo")

    syms_a, edges_a = extractor.extract_from_source(
        sample_code_module_a, "module_a.py"
    )
    store.index_file("module_a.py", syms_a, edges_a)

    syms_b, edges_b = extractor.extract_from_source(
        sample_code_module_b, "module_b.py"
    )
    store.index_file("module_b.py", syms_b, edges_b)

    analyzer = CodeImpactAnalyzer(store=store)

    # helper_calculate is called by compute_metrics (direct), which is called by run_pipeline (indirect)
    report = analyzer.analyze_symbol_impact(
        symbol_name="helper_calculate", file_path="module_a.py"
    )

    assert "module_b.py::compute_metrics" in report.direct_callers
    assert "module_b.py::run_pipeline" in report.indirect_callers
    assert "module_b.py" in report.affected_files
    assert report.blast_radius >= 3
    assert report.risk_level in (ImpactRiskLevel.LOW, ImpactRiskLevel.MEDIUM)


def test_impact_analysis_tool_facade(
    extractor: AstTopologyExtractor, sample_code_module_b: str
) -> None:
    """Verify the agent meta-tool returns structured dictionary for agents."""
    store = CodeGraphMemoryStore(repo_id="test_repo")
    syms, edges = extractor.extract_from_source(sample_code_module_b, "module_b.py")
    store.index_file("module_b.py", syms, edges)

    tool = CodeImpactAnalysisTool(store=store)
    result = tool.analyze_impact(symbol_name="compute_metrics", file_path="module_b.py")

    assert result["target_symbol_name"] == "compute_metrics"
    assert "module_b.py::run_pipeline" in result["direct_callers"]
    assert isinstance(result["safety_recommendations"], list)
    assert len(result["safety_recommendations"]) > 0


def test_codegraph_asset_snapshot(
    extractor: AstTopologyExtractor, sample_code_module_a: str
) -> None:
    """Verify snapshot generation with version hash."""
    store = CodeGraphMemoryStore(repo_id="myrm_workspace")
    syms, edges = extractor.extract_from_source(sample_code_module_a, "mod.py")
    store.index_file("mod.py", syms, edges)

    asset = store.get_asset_snapshot()
    assert asset.repo_id == "myrm_workspace"
    assert asset.total_symbols == 5
    assert len(asset.version_hash) == 16
