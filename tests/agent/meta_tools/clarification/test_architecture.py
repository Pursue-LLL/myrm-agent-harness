"""Architecture guard: clarification schemas stay free of LangChain adapters."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = ("langchain",)


def _collect_import_modules(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_ask_question_schema_has_no_langchain_imports() -> None:
    schema_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "myrm_agent_harness"
        / "agent"
        / "meta_tools"
        / "clarification"
        / "ask_question.py"
    )
    for module in _collect_import_modules(schema_path):
        assert not any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES), (
            f"ask_question.py must remain schema-only; found import: {module}"
        )
