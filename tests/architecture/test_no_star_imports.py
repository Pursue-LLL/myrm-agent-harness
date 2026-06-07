"""Architecture guard: forbid new wildcard imports in harness source."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_HARNESS_SRC = _REPO_ROOT / "src" / "myrm_agent_harness"

# Transitional core→agent shim modules (explicit re-export, no new entries without review).
_ALLOWED_STAR_IMPORT_FILES = frozenset(
    {
        "agent/artifacts/constants.py",
        "agent/hooks/types.py",
        "agent/streaming/types.py",
        "agent/security/audit.py",
        "agent/security/execution_policy.py",
        "agent/security/path_security.py",
        "agent/security/redact.py",
        "agent/security/safe_exec.py",
        "agent/security/tool_registry.py",
        "agent/security/types.py",
        "agent/security/detection/content_boundary.py",
        "agent/security/detection/leak_detector.py",
        "agent/security/detection/pii_classifier.py",
        "agent/security/detection/prompt_guard.py",
        "agent/security/detection/pseudonym_store.py",
        "agent/security/detection/pseudonymizer.py",
        "agent/security/guards/privacy_tracker.py",
        "agent/security/guards/ssrf_guard.py",
    }
)


def _relative_py_path(py_file: Path) -> str:
    return py_file.relative_to(_HARNESS_SRC).as_posix()


@pytest.mark.architecture
def test_no_unlisted_star_imports() -> None:
    """Wildcard imports are allowed only in the frozen shim allowlist."""
    violations: list[str] = []

    for py_file in sorted(_HARNESS_SRC.rglob("*.py")):
        rel = _relative_py_path(py_file)
        source = py_file.read_text(encoding="utf-8")
        if "import *" not in source:
            continue
        if rel in _ALLOWED_STAR_IMPORT_FILES:
            continue
        violations.append(rel)

    if violations:
        joined = "\n".join(f"  - {path}" for path in violations)
        raise AssertionError(
            "Unexpected wildcard imports detected. Add explicit imports or extend the "
            f"frozen allowlist in test_no_star_imports.py:\n{joined}"
        )


@pytest.mark.architecture
def test_star_import_allowlist_paths_exist() -> None:
    """Allowlist entries must point at real shim files."""
    missing = [rel for rel in _ALLOWED_STAR_IMPORT_FILES if not (_HARNESS_SRC / rel).is_file()]
    assert not missing, f"Stale allowlist paths: {missing}"
