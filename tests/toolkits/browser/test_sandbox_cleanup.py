"""Tests for stale automation sandbox cleanup."""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.browser.doctor import cleanup_stale_automation_sandboxes

_SANDBOXES_PATH = "myrm_agent_harness.toolkits.browser.doctor.sandboxes.Path"
_SEARCH_ROOT = "/private/var/folders"


@contextmanager
def _sandbox_candidates(candidates: Sequence[Path | MagicMock]) -> Iterator[MagicMock]:
    """Make the sandbox search root yield ``candidates``; every other ``Path`` call stays real."""
    search_root = MagicMock()
    search_root.is_dir.return_value = True
    search_root.glob.return_value = list(candidates)

    def resolve(*args: str, **kwargs: object) -> Path | MagicMock:
        if args and args[0] == _SEARCH_ROOT:
            return search_root
        return Path(*args, **kwargs)

    with patch(_SANDBOXES_PATH, side_effect=resolve):
        yield search_root


def test_cleanup_stale_automation_sandboxes_dry_run(tmp_path: Path) -> None:
    """Should discover stale sandboxes in dry-run mode without deleting them."""
    test_sandbox = tmp_path / "com.google.Chrome.code_sign_clone"
    test_sandbox.mkdir(parents=True)
    (test_sandbox / "sample.txt").write_text("dummy payload")

    with _sandbox_candidates([test_sandbox]):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=True)

    assert result["dry_run"] is True
    assert result["candidates_inspected"] >= 1
    assert result["pruned"] >= 1
    assert result["reclaimed_bytes"] > 0
    assert test_sandbox.exists()


def test_cleanup_stale_automation_sandboxes_post_assertion_failure(tmp_path: Path) -> None:
    """Should record failure and zero reclaimed_bytes when candidate exists after rmtree."""
    test_sandbox = tmp_path / "com.google.Chrome.code_sign_clone"
    test_sandbox.mkdir(parents=True)
    (test_sandbox / "sample.txt").write_text("dummy payload")

    # rmtree is mocked out, simulating a directory the OS refuses to remove
    with _sandbox_candidates([test_sandbox]), patch("shutil.rmtree"):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=False)

    assert result["pruned"] == 0
    assert result["reclaimed_bytes"] == 0
    assert len(result["failed"]) == 1
    assert result["failed"][0]["reason"] == "directory_still_exists_after_rmtree"


def test_cleanup_stale_automation_sandboxes_glob_wildcard(tmp_path: Path) -> None:
    """Should discover both Chrome and Patchright Chromium code_sign_clone variants."""
    chrome_clone = tmp_path / "com.google.Chrome.code_sign_clone"
    chromium_clone = tmp_path / "org.chromium.Chromium.code_sign_clone"
    chrome_clone.mkdir(parents=True)
    chromium_clone.mkdir(parents=True)

    with _sandbox_candidates([chrome_clone, chromium_clone]) as search_root:
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=True)

    assert result["candidates_inspected"] == 2
    search_root.glob.assert_called_once_with("*/*/*/*.code_sign_clone")


def test_cleanup_stale_automation_sandboxes_dry_run_sampling(tmp_path: Path) -> None:
    """When candidates > 3, dry_run uses average of first 3 samples to avoid I/O storms."""
    sandboxes: list[Path | MagicMock] = []
    for i in range(5):
        s_dir = tmp_path / f"test_{i}.code_sign_clone"
        s_dir.mkdir()
        # Each sandbox gets a 1000-byte file
        (s_dir / "test.bin").write_bytes(b"x" * 1000)
        sandboxes.append(s_dir)

    with _sandbox_candidates(sandboxes):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=True)

    assert result["candidates_inspected"] == 5
    assert result["pruned"] == 5
    # 5 sandboxes * 1000 bytes sampled average = 5000 bytes
    assert result["reclaimed_bytes"] == 5000


def test_mac_app_code_sign_clone_flag_on_darwin() -> None:
    """Should ensure --disable-features=MacAppCodeSignClone is included in launch args on darwin."""
    from myrm_agent_harness.toolkits.browser.pool.browser_pool import _DEFAULT_LAUNCH_OPTIONS

    if sys.platform == "darwin":
        args = _DEFAULT_LAUNCH_OPTIONS.get("args", [])
        assert isinstance(args, list)
        assert "--disable-features=MacAppCodeSignClone" in args


def test_cleanup_stale_automation_sandboxes_versioned_sub_clones(tmp_path: Path) -> None:
    """Should discover individual versioned sub-sandboxes within code_sign_clone parent directory."""
    parent_dir = tmp_path / "com.google.Chrome.code_sign_clone"
    parent_dir.mkdir(parents=True)
    sub1 = parent_dir / "code_sign_clone.01ABC"
    sub2 = parent_dir / "code_sign_clone.02DEF"
    sub1.mkdir()
    sub2.mkdir()
    (sub1 / "binary.bin").write_bytes(b"x" * 2000)
    (sub2 / "binary.bin").write_bytes(b"y" * 3000)

    with _sandbox_candidates([parent_dir]):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=False)

    assert result["dry_run"] is False
    assert result["candidates_inspected"] == 2
    assert result["pruned"] == 2
    assert result["reclaimed_bytes"] == 5000
    assert not sub1.exists()
    assert not sub2.exists()
    assert not parent_dir.exists()


def test_cleanup_stale_automation_sandboxes_skips_active_locked_sandbox() -> None:
    """Should skip pruning sandboxes currently held open by an active process."""
    candidate = MagicMock()
    candidate.exists.return_value = True
    candidate.stat.return_value = MagicMock(st_mtime=0.0)
    candidate.rglob.return_value = []
    candidate.configure_mock(**{"__str__.return_value": "/private/var/folders/sub/test.code_sign_clone"})

    with _sandbox_candidates([candidate]), patch("subprocess.run", return_value=MagicMock(returncode=0)) as lsof:
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=False)

    assert result["pruned"] == 0
    assert result["reclaimed_bytes"] == 0
    lsof.assert_called_once()
