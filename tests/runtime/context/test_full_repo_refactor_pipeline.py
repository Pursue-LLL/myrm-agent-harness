"""Comprehensive unit test suite for native 1M long-context full-repo refactor pipeline."""

import hashlib
import os
import shutil
import tempfile
from collections.abc import Generator

import pytest

from myrm_agent_harness.runtime.context.cross_file_diff_applier import (
    CrossFileDiffAtomicApplier,
)
from myrm_agent_harness.runtime.context.full_repo_ast_packer import (
    FullRepoAstPacker,
)
from myrm_agent_harness.runtime.context.full_repo_attention_anchor import (
    AstDriftToleranceAligner,
    AttentionAnchorInjector,
)
from myrm_agent_harness.runtime.context.full_repo_refactor_pipeline import (
    NativeMillionTokenFullRepoRefactorPipeline,
)
from myrm_agent_harness.runtime.context.full_repo_refactor_types import (
    FileAtomicDiff,
    RefactorPlanBundle,
    RepoSymbolKind,
)


@pytest.fixture
def temp_sample_repo() -> Generator[str]:
    """Create a temporary multi-file project with cross-file imports."""
    temp_dir = tempfile.mkdtemp(prefix="test_repo_")

    # File 1: core_service.py (High fan-in core dependency)
    core_content = (
        '"""Core business logic service."""\n\n'
        "class CorePaymentGateway:\n"
        '    """Processes transactions securely."""\n'
        "    def process_transaction(self, amount: float) -> str:\n"
        '        return f"OK-{amount}"\n'
    )
    with open(os.path.join(temp_dir, "core_service.py"), "w", encoding="utf-8") as f:
        f.write(core_content)

    # File 2: checkout.py (Depends on core_service)
    checkout_content = (
        "import core_service\n\n"
        "def checkout_cart(total: float) -> str:\n"
        "    gateway = core_service.CorePaymentGateway()\n"
        "    return gateway.process_transaction(total)\n"
    )
    with open(os.path.join(temp_dir, "checkout.py"), "w", encoding="utf-8") as f:
        f.write(checkout_content)

    # File 3: subscription.py (Also depends on core_service)
    sub_content = (
        "from core_service import CorePaymentGateway\n\n"
        "def renew_sub(fee: float) -> str:\n"
        "    gw = CorePaymentGateway()\n"
        "    return gw.process_transaction(fee)\n"
    )
    with open(os.path.join(temp_dir, "subscription.py"), "w", encoding="utf-8") as f:
        f.write(sub_content)

    # File 4: utils.ts (TypeScript file)
    ts_content = (
        "export class FormatUtils {\n"
        "  format(val: string): string {\n"
        "    return val.trim();\n"
        "  }\n"
        "}\n"
    )
    with open(os.path.join(temp_dir, "utils.ts"), "w", encoding="utf-8") as f:
        f.write(ts_content)

    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_full_repo_ast_packer(temp_sample_repo: str) -> None:
    """Test AST symbol extraction and cross-file dependency mapping."""
    packer = FullRepoAstPacker()
    topology = packer.scan_and_analyze(temp_sample_repo)

    assert topology.total_files == 4
    assert topology.total_lines > 15
    assert topology.estimated_total_tokens > 20

    # Validate Python symbols
    core_node = topology.file_nodes.get("core_service.py")
    assert core_node is not None
    assert any(s.name == "CorePaymentGateway" and s.kind == RepoSymbolKind.CLASS for s in core_node.symbols)

    # Validate TS symbols
    ts_node = topology.file_nodes.get("utils.ts")
    assert ts_node is not None
    assert any(s.name == "FormatUtils" and s.kind == RepoSymbolKind.CLASS for s in ts_node.symbols)

    # Validate cross-file dependency detection
    checkout_deps = topology.cross_file_dependencies.get("checkout.py", set())
    assert "core_service.py" in checkout_deps
    sub_deps = topology.cross_file_dependencies.get("subscription.py", set())
    assert "core_service.py" in sub_deps

    outline = packer.generate_topology_outline(topology)
    assert "# REPOSITORY AST TOPOLOGY" in outline
    assert "core_service.py" in outline
    assert "CorePaymentGateway" in outline


def test_attention_anchor_injector(temp_sample_repo: str) -> None:
    """Test extraction and rendering of high-fan-in semantic anchors."""
    packer = FullRepoAstPacker()
    topology = packer.scan_and_analyze(temp_sample_repo)

    injector = AttentionAnchorInjector(min_fan_in=2)
    anchors = injector.extract_semantic_anchors(topology)

    assert len(anchors) >= 1
    core_anchor = anchors[0]
    assert core_anchor.symbol_name == "CorePaymentGateway"
    assert core_anchor.file_path == "core_service.py"
    assert len(core_anchor.fan_in_references) == 2

    rendered = injector.render_anchors_block(anchors)
    assert "<attention_anchors>" in rendered
    assert 'symbol="CorePaymentGateway"' in rendered
    assert "checkout.py" in rendered
    assert "subscription.py" in rendered


def test_ast_drift_tolerance_aligner() -> None:
    """Test code slice location with whitespace differences and line drift."""
    aligner = AstDriftToleranceAligner(search_window_lines=10)
    code = (
        "def header():\n"
        "    return 1\n\n"
        "class TargetWorker:\n"
        "    def run(self):\n"
        "        # original comment\n"
        "        res = 42\n"
        "        return res\n\n"
        "def footer():\n"
        "    return 2\n"
    )

    # 1. Exact match
    res_exact = aligner.find_target_slice(code, "res = 42\n        return res")
    assert res_exact is not None
    start, end = res_exact
    assert code[start:end] == "res = 42\n        return res"

    # 2. Line drift with whitespace fluctuation
    target_drifted = "res = 42\nreturn res"
    res_fuzzy = aligner.find_target_slice(
        code,
        target_snippet=target_drifted,
        line_hint=12,  # Drifted line hint
        symbol_anchor_name="TargetWorker",
    )
    assert res_fuzzy is not None
    s_fuzz, e_fuzz = res_fuzzy
    assert "res = 42" in code[s_fuzz:e_fuzz]


def test_cross_file_atomic_diff_applier_success(temp_sample_repo: str) -> None:
    """Test successful atomic multi-file refactoring."""
    applier = CrossFileDiffAtomicApplier()

    with open(os.path.join(temp_sample_repo, "core_service.py"), encoding="utf-8") as f:
        core_orig = f.read()
    core_hash = hashlib.sha256(core_orig.encode("utf-8")).hexdigest()

    # Plan: rename process_transaction to execute_payment in core_service and checkout
    plan = RefactorPlanBundle(
        plan_id="PLAN-001",
        goal_description="Rename payment method across codebase",
        diffs=[
            FileAtomicDiff(
                file_path="core_service.py",
                expected_base_hash=core_hash,
                symbol_anchor_name="CorePaymentGateway",
                target_snippet="def process_transaction(self, amount: float) -> str:",
                replacement_snippet="def execute_payment(self, amount: float) -> str:",
            ),
            FileAtomicDiff(
                file_path="checkout.py",
                target_snippet="gateway.process_transaction(total)",
                replacement_snippet="gateway.execute_payment(total)",
            ),
        ],
    )

    result = applier.apply_plan(temp_sample_repo, plan)
    assert result.success is True
    assert set(result.applied_files) == {"core_service.py", "checkout.py"}
    assert result.error_message is None

    # Verify disk content changed
    with open(os.path.join(temp_sample_repo, "core_service.py"), encoding="utf-8") as f:
        assert "def execute_payment(" in f.read()
    with open(os.path.join(temp_sample_repo, "checkout.py"), encoding="utf-8") as f:
        assert "gateway.execute_payment(total)" in f.read()


def test_cross_file_atomic_diff_applier_rollback_on_preflight_fail(temp_sample_repo: str) -> None:
    """Test full abort and zero modification when one file fails preflight check."""
    applier = CrossFileDiffAtomicApplier()

    with open(os.path.join(temp_sample_repo, "core_service.py"), encoding="utf-8") as f:
        core_orig = f.read()
    core_hash = hashlib.sha256(core_orig.encode("utf-8")).hexdigest()

    plan = RefactorPlanBundle(
        plan_id="PLAN-002",
        goal_description="Conflict refactor",
        diffs=[
            FileAtomicDiff(
                file_path="core_service.py",
                expected_base_hash=core_hash,
                target_snippet="def process_transaction",
                replacement_snippet="def execute_payment",
            ),
            FileAtomicDiff(
                file_path="checkout.py",
                expected_base_hash="bad_hash_1234567890abcdef",  # Mismatch!
                target_snippet="gateway.process_transaction",
                replacement_snippet="gateway.execute_payment",
            ),
        ],
    )

    result = applier.apply_plan(temp_sample_repo, plan)
    assert result.success is False
    assert "Base hash mismatch" in (result.error_message or "")

    # Crucial assertion: core_service.py was NOT modified on disk
    with open(os.path.join(temp_sample_repo, "core_service.py"), encoding="utf-8") as f:
        assert f.read() == core_orig


def test_native_million_token_pipeline_end_to_end(temp_sample_repo: str) -> None:
    """Test end-to-end packing and atomic refactoring facade."""
    pipeline = NativeMillionTokenFullRepoRefactorPipeline()

    packed = pipeline.pack_repo_for_refactor(temp_sample_repo, max_tokens=500_000)
    assert packed.total_estimated_tokens > 0
    assert len(packed.structured_files) == 4
    assert "core_service.py" in packed.structured_files
    assert "<file path=\"core_service.py\"" in packed.full_packed_prompt
    assert "<attention_anchors>" in packed.full_packed_prompt

    # Execute atomic refactor via pipeline
    plan = RefactorPlanBundle(
        plan_id="PLAN-E2E",
        goal_description="Update utils format",
        diffs=[
            FileAtomicDiff(
                file_path="utils.ts",
                target_snippet="return val.trim();",
                replacement_snippet="return val.trim().toLowerCase();",
            )
        ],
    )

    apply_res = pipeline.apply_refactor(temp_sample_repo, plan)
    assert apply_res.success is True
    assert "utils.ts" in apply_res.applied_files

    with open(os.path.join(temp_sample_repo, "utils.ts"), encoding="utf-8") as f:
        assert "toLowerCase()" in f.read()
