"""Unit tests for VirtualPagedCodeContextTieringAndSwapEngine.

Validates AST symbol stub extraction, standard virtual code pagination,
LRU page-out under strict token budgets, page-fault resolution, and
context stability audits across multi-file operations.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.ast_symbol_stub_extractor import (
    AstSymbolStubExtractor,
)
from myrm_agent_harness.runtime.context.code_context_pager import (
    CodeContextPager,
)
from myrm_agent_harness.runtime.context.virtual_page_swap_manager import (
    VirtualPageSwapManager,
)
from myrm_agent_harness.runtime.context.virtual_paged_code_types import (
    PageLifecycleState,
)


def test_ast_symbol_stub_extractor_python_and_manifest() -> None:
    extractor = AstSymbolStubExtractor()
    code = (
        'class DatabasePool:\n'
        '    """Manages postgres connection pooling."""\n'
        '    pass\n\n'
        'async def fetch_record(query: str, timeout: int = 30) -> dict:\n'
        '    """Fetches single record asynchronously."""\n'
        '    return {}\n\n'
        'def sync_helper():\n'
        '    pass\n'
    )
    stubs = extractor.extract_stubs("db/pool.py", code)
    assert len(stubs) == 3

    assert stubs[0].symbol_name == "DatabasePool"
    assert stubs[0].kind == "class"
    assert "class DatabasePool" in stubs[0].signature
    assert "Manages postgres" in stubs[0].doc_summary

    assert stubs[1].symbol_name == "fetch_record"
    assert stubs[1].kind == "function"
    assert "async def fetch_record" in stubs[1].signature
    assert "Fetches single record" in stubs[1].doc_summary

    assert stubs[2].symbol_name == "sync_helper"
    assert stubs[2].kind == "function"

    manifest = extractor.format_stubs_manifest("db/pool.py", stubs)
    assert "Stub: db/pool.py (Archived)" in manifest
    assert "Class class DatabasePool" in manifest
    assert "Function async def fetch_record" in manifest


def test_ast_symbol_stub_extractor_regex_fallback() -> None:
    extractor = AstSymbolStubExtractor()
    ts_code = (
        'export class TokenRouter {\n'
        '  route() {}\n'
        '}\n'
        'export function calculateTax(rate: number) {\n'
        '  return rate * 1.1;\n'
        '}\n'
    )
    stubs = extractor.extract_stubs("services/router.ts", ts_code)
    assert len(stubs) == 2
    assert stubs[0].symbol_name == "TokenRouter"
    assert stubs[0].kind == "class"
    assert stubs[1].symbol_name == "calculateTax"
    assert stubs[1].kind == "function"


def test_code_context_pager_multi_page_splitting() -> None:
    pager = CodeContextPager(page_size_chars=100)  # small page size for unit testing
    code = (
        'def func_a():\n'
        '    # Some payload\n'
        '    return 1\n' * 5
        + '\ndef func_b():\n'
        '    # More payload\n'
        '    return 2\n' * 5
    )
    pages = pager.paginate_file("handlers/process.py", code)
    assert len(pages) >= 2
    assert all(p.file_path == "handlers/process.py" for p in pages)
    assert pages[0].token_count > 0
    assert pages[0].lifecycle_state == PageLifecycleState.CORE_RESIDENT
    assert "page_index" in pages[0].metadata


def test_virtual_page_swap_manager_lru_and_page_fault() -> None:
    manager = VirtualPageSwapManager(max_core_tokens=40)

    # File A: ~25 tokens
    code_a = (
        'class ServiceA:\n'
        '    """First core service."""\n'
        '    pass\n\n'
        'def handle_a():\n'
        '    return "A" * 50\n'
    )
    pages_a = manager.load_file("services/a.py", code_a)
    assert len(pages_a) >= 1
    assert pages_a[0].lifecycle_state == PageLifecycleState.CORE_RESIDENT

    # File B: ~25 tokens (will push total tokens ~50 > 40, causing ServiceA to page-out)
    code_b = (
        'class ServiceB:\n'
        '    """Second core service."""\n'
        '    pass\n\n'
        'def handle_b():\n'
        '    return "B" * 50\n'
    )
    pages_b = manager.load_file("services/b.py", code_b)
    assert len(pages_b) >= 1

    audit_initial = manager.audit_context_stability()
    assert audit_initial.archived_pages_count >= 1
    assert audit_initial.resident_pages_count >= 1
    assert audit_initial.is_budget_exceeded is False

    # Check that context render contains stub for archived file and code for resident file
    rendered = manager.render_active_context()
    assert "Stub: services/a.py (Archived)" in rendered or "services/a.py" in rendered
    assert "ServiceB" in rendered

    # Trigger Page Fault by resolving symbol from archived ServiceA
    event = manager.resolve_symbol("ServiceA")
    assert event.resolved is True
    assert "Page fault" in event.reason

    audit_after = manager.audit_context_stability()
    assert audit_after.total_page_faults >= 1
    assert audit_after.is_budget_exceeded is False


def test_virtual_page_swap_manager_multi_file_stability_stress() -> None:
    manager = VirtualPageSwapManager(max_core_tokens=400)

    # Simulate 25 distinct files being loaded and edited sequentially
    for i in range(25):
        file_path = f"modules/component_{i:02d}.py"
        code = (
            f"class Component{i:02d}:\n"
            f'    """Component module {i}."""\n'
            f"    def execute(self):\n"
            f'        return "result_{i}" * 50\n\n'
            f"def helper_{i:02d}():\n"
            f"    return {i}\n"
        )
        manager.load_file(file_path, code)

    # Resolve various symbols triggering sporadic page-faults
    manager.resolve_symbol("Component02")
    manager.resolve_symbol("Component10")
    manager.resolve_symbol("Component05")

    audit = manager.audit_context_stability()
    assert audit.archived_pages_count > 10
    assert audit.resident_pages_count > 0
    assert audit.is_budget_exceeded is False
    assert audit.total_page_faults >= 1
    # Variance ratio strictly maintained within stability limit (≤ 20% or 0.20)
    assert audit.stability_variance_ratio <= 0.20
