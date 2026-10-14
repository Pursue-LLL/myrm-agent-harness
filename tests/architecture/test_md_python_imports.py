"""Architecture test: every harness import shown in a tracked markdown python fence must resolve.

Integrators copy doc examples verbatim and no other gate executes them, so a renamed class or a moved
module leaves a snippet that fails with ``ImportError`` on first use. Each fence is parsed, never run, and
its ``myrm_agent_harness`` imports are resolved by the same static engine as
``scripts/check_import_resolvability.py``. Only imports are checked, not call signatures.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Mapping
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.import_resolvability_engine import analyze
from scripts.tool_registry_config import HARNESS_SRC

_PACKAGE = "myrm_agent_harness"
_SNIPPETS = "docs_snippets"
_FENCE = re.compile(r"^[ \t]*```(?:python3?|py)[ \t]*\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
_HARNESS_IMPORT = re.compile(rf"^\s*(?:from|import)\s+{_PACKAGE}\b", re.MULTILINE)


def _python_fences(text: str) -> list[tuple[int, str]]:
    """Return ``(1-based line of the first code line, dedented body)`` for every python fence in ``text``."""
    return [
        (text.count("\n", 0, match.start(1)) + 1, textwrap.dedent(match.group(1))) for match in _FENCE.finditer(text)
    ]


def find_unresolved(docs: Mapping[str, str]) -> list[str]:
    """Return one ``doc:line target [reason]`` problem per harness import in ``docs`` that does not resolve.

    A fence that is not valid Python is reported only when it holds a harness import, because that import
    could not be checked; pseudo-code fences without one are ignored.
    """
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / _SNIPPETS
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        origin: dict[str, tuple[str, int, str]] = {}
        for doc, text in docs.items():
            for line, body in _python_fences(text):
                name = f"snippet_{len(origin):05d}.py"
                (package / name).write_text(body, encoding="utf-8")
                origin[name] = (doc, line, body)

        report = analyze({_PACKAGE: HARNESS_SRC, _SNIPPETS: package}, scan=[_SNIPPETS])

    for finding in report.findings:
        doc, line, _ = origin[finding.path.name]
        problems.append(f"{doc}:{line + finding.line - 1}  {finding.target}  [{finding.reason}]")
    for path in report.unparsable:
        doc, line, body = origin[path.name]
        if _HARNESS_IMPORT.search(body):
            problems.append(f"{doc}:{line}  fence is not valid Python, so its harness import cannot be checked")
    return problems


def _tracked_markdown() -> dict[str, str]:
    result = subprocess.run(["git", "ls-files", "*.md"], cwd=_REPO_ROOT, check=True, capture_output=True, text=True)
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {path: (_REPO_ROOT / path).read_text(encoding="utf-8") for path in paths if (_REPO_ROOT / path).is_file()}


@pytest.mark.architecture
def test_tracked_markdown_python_imports_resolve() -> None:
    docs = _tracked_markdown()
    assert any(_python_fences(text) for text in docs.values()), "no python fence found: the fence pattern is broken"
    problems = find_unresolved(docs)
    assert not problems, "doc snippets import harness names that do not exist:\n" + "\n".join(problems)


@pytest.mark.architecture
def test_detector_flags_missing_module_name_and_unparsable_fence() -> None:
    """Self-proof: the detector must not degrade into a no-op that passes every doc."""
    doc = "\n".join(
        [
            "# Title",
            "```python",
            "from myrm_agent_harness.toolkits.storage import LocalStorageBackend",
            "from myrm_agent_harness.toolkits.storage import NoSuchStorage",
            "```",
            "text",
            "   ```python",
            "   import myrm_agent_harness.toolkits.no_such_module",
            "   ```",
            "```python",
            "from myrm_agent_harness.toolkits.storage import (",
            "```",
            "```python",
            "def pseudo(:",
            "```",
        ]
    )
    assert find_unresolved({"doc.md": doc}) == [
        "doc.md:4  myrm_agent_harness.toolkits.storage:NoSuchStorage  [name not defined]",
        "doc.md:8  myrm_agent_harness.toolkits.no_such_module  [module not found]",
        "doc.md:11  fence is not valid Python, so its harness import cannot be checked",
    ]
