"""Boundary check: harness layer must not import from business layer.

The myrm-agent-harness package is a standalone, publishable agent framework.
It must never depend on the business layer (myrm-agent-server, myrm-control-plane).

This test scans all Python files in the harness package and fails if any
business layer import statement is found.

Architecture Reference: ARCHITECTURE.md
Usage Guide: scripts/README.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add tools directory to Python path for importing shared modules
_repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.boundary_check import (
    _build_summary,
    check_file,
    classify_priority,
    collect_imports,
    get_changed_harness_files,
    is_allowed_path,
    is_banned_import,
)

# Root of the harness package
HARNESS_ROOT = Path(__file__).parent.parent.parent / "src" / "myrm_agent_harness"


@pytest.mark.architecture
def test_harness_does_not_import_business_layer() -> None:
    """Verify harness layer does not import from business layer.

    Scans all Python files in src/myrm_agent_harness/ and checks for
    imports from myrm-agent-server or myrm-control-plane.

    Fails with concise error message if violations are found.
    """
    violations: list[str] = []

    for py_file in sorted(HARNESS_ROOT.rglob("*.py")):
        count, messages = check_file(py_file, HARNESS_ROOT, fix=False)
        if count > 0:
            violations.extend(messages)

    if violations:
        error_message = (
            " Boundary violations detected:\n\n" + "\n".join(violations) + "\n\n"
            "Run 'python scripts/boundary_check.py --fix' to auto-fix"
        )
        raise AssertionError(error_message)


class TestBoundaryDetection:
    """Negative testing: ensure the detector itself works correctly."""

    def test_banned_import_detection_exact_match(self) -> None:
        """Test that exact module name matches are detected."""
        assert is_banned_import("myrm_agent_server")
        assert is_banned_import("myrm_control_plane")
        assert is_banned_import("app")

    def test_banned_import_detection_submodule_match(self) -> None:
        """Test that submodule imports are detected."""
        assert is_banned_import("myrm_agent_server.database")
        assert is_banned_import("myrm_control_plane.docker")
        assert is_banned_import("app.platform")

    def test_banned_import_detection_no_false_positives(self) -> None:
        """Test that similar but allowed modules are NOT flagged."""
        assert not is_banned_import("myrm_agent_harness")
        assert not is_banned_import("myrm_agent_harness.runtime")
        assert not is_banned_import("application")
        assert not is_banned_import("my_app")

    def test_whitelist_mode_blocks_new_myrm_modules(self) -> None:
        """Test that new myrm_* modules are automatically blocked (whitelist mode)."""
        # New business modules should be blocked automatically
        assert is_banned_import("myrm_new_business_module")
        assert is_banned_import("myrm_payment_service")
        assert is_banned_import("myrm_analytics")

    def test_whitelist_mode_allows_framework_only(self) -> None:
        """Test that only whitelisted framework modules are allowed."""
        # Allowed: myrm_agent_harness (in whitelist)
        assert not is_banned_import("myrm_agent_harness")
        assert not is_banned_import("myrm_agent_harness.runtime")
        assert not is_banned_import("myrm_agent_harness.toolkits.browser")

        # Blocked: known business modules
        assert is_banned_import("myrm_agent_server")
        assert is_banned_import("myrm_control_plane")
        assert is_banned_import("app")

    def test_third_party_packages_allowed(self) -> None:
        """Test that third-party packages are allowed (not our business layer)."""
        # Standard third-party naming conventions
        assert not is_banned_import("requests")
        assert not is_banned_import("django")
        assert not is_banned_import("flask")
        assert not is_banned_import("numpy")
        assert not is_banned_import("pandas")

    def test_allowed_path_matching(self) -> None:
        """Test that whitelist path matching works correctly."""
        root = Path(__file__).parent.parent.parent

        # Allowed paths
        assert is_allowed_path(root / "tests" / "integration" / "test_api.py", HARNESS_ROOT)
        assert is_allowed_path(root / "tests" / "e2e" / "test_workflow.py", HARNESS_ROOT)
        assert is_allowed_path(root / "scripts" / "benchmark.py", HARNESS_ROOT)
        assert is_allowed_path(root / "benchmarks" / "bench_performance.py", HARNESS_ROOT)

        # Disallowed paths (false positives check)
        assert not is_allowed_path(
            root / "src" / "tests" / "integration_helper.py",
            HARNESS_ROOT,
        )
        assert not is_allowed_path(
            root / "src" / "myrm_agent_harness" / "runtime" / "scripts.py",
            HARNESS_ROOT,
        )
        assert not is_allowed_path(root / "tests" / "unit" / "test_core.py", HARNESS_ROOT)

    def test_collect_imports_basic(self) -> None:
        """Test that collect_imports extracts imports correctly."""
        import tempfile

        test_code = """
from myrm_agent_server import database
import app.platform
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            assert len(imports) == 2
            _linenos, modules = zip(*imports, strict=False)
            assert "myrm_agent_server" in modules
            assert "app.platform" in modules
        finally:
            temp_path.unlink()

    def test_collect_dynamic_imports(self) -> None:
        """Test that dynamic imports are detected."""
        import tempfile

        test_code = """
import importlib

def load_module():
    # Dynamic import should be detected
    mod = importlib.import_module("myrm_agent_server.database")
    return mod

def another_function():
    # __import__ should also be detected
    db = __import__("myrm_control_plane")
    return db
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            # Should detect: importlib, myrm_agent_server.database, myrm_control_plane
            assert len(imports) == 3
            _linenos, modules = zip(*imports, strict=False)
            assert "importlib" in modules
            assert "myrm_agent_server.database" in modules
            assert "myrm_control_plane" in modules
        finally:
            temp_path.unlink()

    def test_dynamic_import_with_variable(self) -> None:
        """Test that dynamic imports with variables are not detected (intentional limitation)."""
        import tempfile

        test_code = """
import importlib

module_name = "myrm_agent_server"
mod = importlib.import_module(module_name)  # Variable - cannot detect statically
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            # Should only detect static import of importlib
            assert len(imports) == 1
            assert imports[0][1] == "importlib"
        finally:
            temp_path.unlink()

    def test_exec_eval_import_detection(self) -> None:
        """Test that imports hidden inside exec/eval are detected."""
        import tempfile

        test_code = """
exec("from myrm_agent_server import database")
exec("import myrm_control_plane")
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            modules = [m for _, m in imports]
            assert "myrm_agent_server" in modules
            assert "myrm_control_plane" in modules
        finally:
            temp_path.unlink()

    def test_exec_eval_no_false_positives(self) -> None:
        """Test that exec/eval without imports are not flagged."""
        import tempfile

        test_code = """
exec("print('hello')")
eval("1 + 2")
exec("x = 42")
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            assert imports == []
        finally:
            temp_path.unlink()

    def test_fstring_import_module_detection(self) -> None:
        """Test that f-string prefixes in importlib.import_module are detected."""
        import tempfile

        test_code = """
import importlib

name = "models"
mod = importlib.import_module(f"app.{name}")
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            modules = [m for _, m in imports]
            assert "importlib" in modules
            assert "app" in modules
        finally:
            temp_path.unlink()


class TestIncrementalDetection:
    """Test suite for git-aware incremental scanning."""

    def test_get_changed_harness_files_returns_list_or_none(self) -> None:
        """Test that get_changed_harness_files returns a list or None."""
        result = get_changed_harness_files(HARNESS_ROOT)
        # In a git repo, should return a list (possibly empty)
        # Outside a git repo, returns None
        assert result is None or isinstance(result, list)

    def test_get_changed_harness_files_filters_to_harness(self) -> None:
        """Test that only harness directory files are returned."""
        result = get_changed_harness_files(HARNESS_ROOT)
        if result is not None:
            harness_prefix = str(HARNESS_ROOT)
            for f in result:
                assert str(f).startswith(harness_prefix), f"File {f} is not under harness root"


class TestSmartReport:
    """Test suite for priority classification and summary report."""

    def test_classify_priority_high(self) -> None:
        """Test that core framework paths are classified as HIGH."""
        assert classify_priority(HARNESS_ROOT / "agent" / "core.py", HARNESS_ROOT) == "HIGH"
        assert classify_priority(HARNESS_ROOT / "runtime" / "monitor.py", HARNESS_ROOT) == "HIGH"
        assert classify_priority(HARNESS_ROOT / "toolkits" / "browser.py", HARNESS_ROOT) == "HIGH"

    def test_classify_priority_medium(self) -> None:
        """Test that non-core paths are classified as MEDIUM."""
        assert classify_priority(HARNESS_ROOT / "infra" / "delivery.py", HARNESS_ROOT) == "MEDIUM"
        assert classify_priority(HARNESS_ROOT / "backends" / "storage.py", HARNESS_ROOT) == "MEDIUM"

    def test_classify_priority_low(self) -> None:
        """Test that test/script paths are classified as LOW."""
        assert classify_priority(HARNESS_ROOT / "tests" / "test_x.py", HARNESS_ROOT) == "LOW"
        assert classify_priority(HARNESS_ROOT / "scripts" / "run.py", HARNESS_ROOT) == "LOW"

    def test_build_summary_groups_by_priority(self) -> None:
        """Test that summary report groups violations by priority."""
        messages = [
            "\n   [HIGH] agent/core.py:10\n     ...\n",
            "\n   [MEDIUM] infra/util.py:5\n     ...\n",
            "\n   [LOW] tests/test.py:1\n     ...\n",
        ]
        report = _build_summary(messages, files_checked=100, total_violations=3)
        assert " HIGH Priority: 1" in report
        assert " MEDIUM Priority: 1" in report
        assert " LOW Priority: 1" in report
        assert "3 violation(s) in 100 files" in report

    def test_build_summary_single_priority(self) -> None:
        """Test summary report with only one priority level."""
        messages = [
            "\n   [HIGH] agent/core.py:10\n     ...\n",
            "\n   [HIGH] agent/tool.py:20\n     ...\n",
        ]
        report = _build_summary(messages, files_checked=50, total_violations=2)
        assert " HIGH Priority: 2" in report
        # MEDIUM and LOW sections should not appear (0 violations)
        assert " MEDIUM Priority:" not in report
        assert " LOW Priority:" not in report
