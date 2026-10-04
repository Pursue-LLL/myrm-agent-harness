"""Cross-repo markdown path gate.

The harness CI runs md-ref validation for harness + server (see
``test_validate_arch_inventory.py``). The remaining sibling repos
(frontend, control-plane, brand) carry architecture docs whose relative links
must resolve on a monorepo checkout just the same; this gate extends the same
validator to them so a broken ``[label](path)`` cannot silently regress.

Each repo is skipped when its checkout is absent, keeping standalone harness
clones green."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
_monorepo_root = _repo_root.parent

# Sibling repos whose docs are validated alongside the harness/server gates.
_SIBLING_REPOS = (
    _monorepo_root / "myrm-agent" / "myrm-agent-frontend",
    _monorepo_root / "myrm-control-plane",
    _monorepo_root / "myrm-agent-brand",
)


@pytest.mark.architecture
@pytest.mark.parametrize("repo_root", _SIBLING_REPOS, ids=lambda p: p.name)
def test_sibling_repo_md_refs_resolve(repo_root: Path) -> None:
    """Every sibling repo's markdown path references resolve in the monorepo."""
    if not repo_root.is_dir():
        pytest.skip(f"{repo_root.name} not checked out next to harness")

    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(repo_root), "--md-refs"],
        cwd=_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
