"""Architecture tests for publish tag vs pyproject version gate."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.verify_release_tag import main


def test_tag_gate_skips_non_tag_ref(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REF", raising=False)
    assert main() == 0

    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert main() == 0


def test_tag_gate_passes_when_versions_match(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v0.1.0rc5")
    assert main() == 0


def test_tag_gate_fails_on_version_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v9.9.9")
    assert main() == 1
