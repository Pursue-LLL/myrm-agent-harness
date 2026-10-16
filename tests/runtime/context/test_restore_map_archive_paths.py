"""Tests for archive path matching under the persistent root in effect."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.restore_map_contract import archive_path_matches
from myrm_agent_harness.runtime.paths.execution_paths import PERSISTENT_ROOT_ENV


def test_matches_rooted_and_root_relative_forms_under_default_root() -> None:
    assert archive_path_matches("/persistent/.context/s1/compacted/a.txt", ".context/s1/compacted/a.txt")
    assert archive_path_matches(".context/s1/compacted/a.txt", "/persistent/.context/s1/compacted/a.txt")


def test_matches_rooted_and_root_relative_forms_under_relocated_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, "/var/state/harness")

    assert archive_path_matches("/var/state/harness/.context/s1/compacted/a.txt", ".context/s1/compacted/a.txt")
    assert archive_path_matches(".context/s1/compacted/a.txt", "/var/state/harness/.context/s1/compacted/a.txt")


def test_different_archives_do_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, "/var/state/harness")

    assert not archive_path_matches("/var/state/harness/.context/s1/compacted/a.txt", ".context/s1/compacted/b.txt")
