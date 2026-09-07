from pathlib import Path
from myrm_agent_harness.backends.skills.code_analysis import (
    PythonAstTopologyScanner,
)


def test_topology_scanner_detects_dead_code(tmp_path: Path) -> None:
    # 1. Create a module with referenced and unreferenced functions
    mod_a = tmp_path / "module_a.py"
    mod_a.write_text(
        """
def used_helper() -> str:
    return "active"

def dead_function_never_called() -> int:
    return 42

class DeadClass:
    pass
""",
        encoding="utf-8",
    )

    main_mod = tmp_path / "main.py"
    main_mod.write_text(
        """
from module_a import used_helper

def run_app() -> None:
    print(used_helper())
""",
        encoding="utf-8",
    )

    # 2. Run AST scanner
    report = PythonAstTopologyScanner.scan_directory(tmp_path)

    # 3. Assertions
    assert report.total_files_scanned == 2
    unref_names = {sym.name for sym in report.unreferenced_symbols}
    assert "dead_function_never_called" in unref_names
    assert "DeadClass" in unref_names
    assert "used_helper" not in unref_names
    assert "run_app" in unref_names  # main.run_app is top-level definition


def test_topology_scanner_empty_dir(tmp_path: Path) -> None:
    report = PythonAstTopologyScanner.scan_directory(tmp_path / "non_existent")
    assert report.total_files_scanned == 0
    assert len(report.definitions) == 0
