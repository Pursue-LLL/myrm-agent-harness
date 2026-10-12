"""Tests for stale automation sandbox cleanup."""

from __future__ import annotations

import os
import plistlib
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
    check_orphan_processes,
    cleanup_stale_automation_sandboxes,
)
from myrm_agent_harness.toolkits.browser.doctor.sandboxes import _running_app_bundle_ids

_SANDBOXES_PATH = "myrm_agent_harness.toolkits.browser.doctor.sandboxes.Path"
_RUNNING_IDS_PATH = "myrm_agent_harness.toolkits.browser.doctor.sandboxes._running_app_bundle_ids"
_SEARCH_ROOT = "/private/var/folders"
_CHROME_ID = "com.google.Chrome"


@pytest.fixture(autouse=True)
def _no_running_browsers() -> Iterator[None]:
    """Pin liveness so no test depends on the browsers running on the machine that executes it."""
    with patch(_RUNNING_IDS_PATH, return_value=frozenset()):
        yield


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


def _clone_with_payload(root: Path, bundle_id: str, sub_name: str = "code_sign_clone.AbC123") -> Path:
    """Create ``<bundle_id>.code_sign_clone/<sub_name>`` holding a 1000-byte file and return the sub clone."""
    sub_clone = root / f"{bundle_id}.code_sign_clone" / sub_name
    sub_clone.mkdir(parents=True)
    (sub_clone / "binary.bin").write_bytes(b"x" * 1000)
    return sub_clone


def test_prune_keeps_clone_of_running_browser_and_prunes_the_rest(tmp_path: Path) -> None:
    """A clone belongs to its running browser, so only clones of browsers that are gone are removed."""
    live = _clone_with_payload(tmp_path, _CHROME_ID)
    leaked = _clone_with_payload(tmp_path, "org.chromium.Chromium")

    with (
        _sandbox_candidates([live.parent, leaked.parent]),
        patch(_RUNNING_IDS_PATH, return_value=frozenset({_CHROME_ID})),
    ):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=False)

    assert live.exists()
    assert not leaked.exists()
    assert result["candidates_inspected"] == 2
    assert result["pruned"] == 1
    assert result["reclaimed_bytes"] == 1000


def test_dry_run_does_not_count_clone_of_running_browser(tmp_path: Path) -> None:
    """The preview applies the same rule as the prune, so it never reports a clone the prune would keep."""
    live = _clone_with_payload(tmp_path, _CHROME_ID)

    with _sandbox_candidates([live.parent]), patch(_RUNNING_IDS_PATH, return_value=frozenset({_CHROME_ID})):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=True)

    assert result["pruned"] == 0
    assert result["reclaimed_bytes"] == 0
    assert live.exists()


@pytest.mark.parametrize("dry_run", [True, False])
def test_unknown_liveness_treats_every_clone_as_in_use(tmp_path: Path, dry_run: bool) -> None:
    """When the process table cannot be read nothing may be reported or removed."""
    clone = _clone_with_payload(tmp_path, "org.chromium.Chromium")

    with _sandbox_candidates([clone.parent]), patch(_RUNNING_IDS_PATH, return_value=None):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=dry_run)

    assert result["pruned"] == 0
    assert result["reclaimed_bytes"] == 0
    assert clone.exists()


def test_bare_clone_directory_is_matched_by_its_own_name(tmp_path: Path) -> None:
    """A clone directory without versioned sub clones is its own unit and still maps to its browser."""
    bare = tmp_path / f"{_CHROME_ID}.code_sign_clone"
    bare.mkdir()
    (bare / "binary.bin").write_bytes(b"x" * 10)

    with _sandbox_candidates([bare]), patch(_RUNNING_IDS_PATH, return_value=frozenset({_CHROME_ID})):
        result = cleanup_stale_automation_sandboxes(max_age_hours=0.0, dry_run=False)

    assert result["pruned"] == 0
    assert bare.exists()


def test_doctor_check_reports_only_clones_without_a_running_browser(tmp_path: Path) -> None:
    """The Doctor warning and the cleanup agree: a clone of a running browser is never flagged as stale."""
    live = _clone_with_payload(tmp_path, _CHROME_ID)
    os.utime(live, (0, 0))
    find_orphans = "myrm_agent_harness.toolkits.browser.doctor.orphan_check.find_orphan_automation_processes"

    with patch(find_orphans, return_value=[]), _sandbox_candidates([live.parent]):
        with patch(_RUNNING_IDS_PATH, return_value=frozenset({_CHROME_ID})):
            while_running = check_orphan_processes()
        after_exit = check_orphan_processes()

    assert while_running.status is CheckStatus.OK
    assert after_exit.status is CheckStatus.WARNING
    assert (after_exit.details or {})["stale_sandboxes"] == 1


def _make_app(root: Path, name: str, bundle_id: str | None) -> Path:
    """Create ``<name>.app`` with an ``Info.plist`` carrying ``bundle_id`` (omitted when ``None``)."""
    contents = root / f"{name}.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    if bundle_id is not None:
        (contents / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": bundle_id}))
    return root / f"{name}.app"


def _process_table(executables: Iterable[str | None]) -> list[SimpleNamespace]:
    return [SimpleNamespace(info={"exe": exe}) for exe in executables]


def test_running_bundle_ids_are_read_from_the_main_executable(tmp_path: Path) -> None:
    """Each running ``.app`` executable maps to its ``CFBundleIdentifier``; anything unreadable is ignored."""
    chrome = _make_app(tmp_path, "Chrome", _CHROME_ID)
    helper = _make_app(chrome / "Contents" / "Frameworks", "Helper", f"{_CHROME_ID}.helper")
    no_plist = _make_app(tmp_path, "NoPlist", None)
    corrupt = _make_app(tmp_path, "Corrupt", None)
    (corrupt / "Contents" / "Info.plist").write_bytes(b"not a plist")
    table = _process_table(
        [
            f"{chrome}/Contents/MacOS/Chrome",
            f"{chrome}/Contents/MacOS/Chrome",
            f"{helper}/Contents/MacOS/Helper",
            f"{no_plist}/Contents/MacOS/NoPlist",
            f"{corrupt}/Contents/MacOS/Corrupt",
            "/usr/bin/python3",
            None,
        ]
    )

    with patch("psutil.process_iter", return_value=table):
        bundle_ids = _running_app_bundle_ids()

    assert bundle_ids == frozenset({_CHROME_ID, f"{_CHROME_ID}.helper"})


def test_running_bundle_ids_is_unknown_without_psutil() -> None:
    """Without psutil liveness cannot be established, which callers treat as in use."""
    with patch.dict(sys.modules, {"psutil": None}):
        assert _running_app_bundle_ids() is None


def test_running_bundle_ids_is_unknown_when_the_process_table_fails() -> None:
    """A failing process walk must not look like 'nothing is running'."""
    with patch("psutil.process_iter", side_effect=OSError("denied")):
        assert _running_app_bundle_ids() is None


def test_running_bundle_ids_reads_the_real_process_table() -> None:
    """Smoke test against the real psutil API: the walk succeeds and yields plain identifier strings."""
    bundle_ids = _running_app_bundle_ids()

    assert bundle_ids is not None
    assert all(isinstance(bundle_id, str) and bundle_id for bundle_id in bundle_ids)
