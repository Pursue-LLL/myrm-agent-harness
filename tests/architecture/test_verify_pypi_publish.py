"""Architecture tests for post-upload PyPI verification."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.platforms import (  # noqa: E402
    ALL_PLATFORMS,
    MUSL_PLATFORMS,
    PUBLISH_PLATFORMS,
    PYPI_VERIFY_PLATFORMS,
)
from scripts.verify_pypi_publish import (  # noqa: E402
    _expected_packages,
    missing_packages,
    verify_platform_keys,
    verify_published,
)


def test_platform_publish_verify_semantics() -> None:
    assert len(PUBLISH_PLATFORMS) == len(ALL_PLATFORMS) == 8
    assert len(PYPI_VERIFY_PLATFORMS) == 6
    assert len(MUSL_PLATFORMS) == 2
    assert all(key.endswith("-musl") for key in MUSL_PLATFORMS)
    assert set(PYPI_VERIFY_PLATFORMS) | set(MUSL_PLATFORMS) == set(ALL_PLATFORMS)


def test_verify_platform_keys_excludes_unindexed_musl() -> None:
    with patch("scripts.verify_pypi_publish.pypi_package_exists", return_value=False):
        assert verify_platform_keys("0.1.0rc5") == PYPI_VERIFY_PLATFORMS


def test_verify_platform_keys_includes_indexed_musl() -> None:
    def fake_exists(package: str, version: str, *, user_agent: str) -> bool:
        return package.startswith("myrm-agent-harness-core-linux-") and "musl" in package

    with patch("scripts.verify_pypi_publish.pypi_package_exists", side_effect=fake_exists):
        keys = verify_platform_keys("0.1.0rc5")
    assert keys == PYPI_VERIFY_PLATFORMS + MUSL_PLATFORMS


def test_expected_packages_count_without_musl() -> None:
    with patch("scripts.verify_pypi_publish.pypi_package_exists", return_value=False):
        assert len(_expected_packages("0.1.0rc2")) == 7


def test_expected_packages_count_with_musl() -> None:
    def fake_exists(package: str, version: str, *, user_agent: str) -> bool:
        return "musl" in package

    with patch("scripts.verify_pypi_publish.pypi_package_exists", side_effect=fake_exists):
        assert len(_expected_packages("0.1.0rc2")) == 9


def test_missing_packages_reports_all_absent() -> None:
    with (
        patch("scripts.verify_pypi_publish.pypi_package_exists", return_value=False),
        patch("scripts.verify_pypi_publish.release_has_compiled_core_extra", return_value=False),
    ):
        missing = missing_packages("0.1.0rc2")
    assert len(missing) == 8
    assert missing[0] == "myrm-agent-harness==0.1.0rc2"


def test_release_extra_missing_is_reported() -> None:
    with (
        patch("scripts.verify_pypi_publish.pypi_package_exists", return_value=True),
        patch("scripts.verify_pypi_publish.release_has_compiled_core_extra", return_value=False),
    ):
        missing = missing_packages("0.1.0rc2")
    assert missing == ["myrm-agent-harness==0.1.0rc2 missing [compiled-core] extra metadata"]


def test_verify_published_succeeds_when_complete() -> None:
    with patch("scripts.verify_pypi_publish.missing_packages", return_value=[]):
        verify_published("0.1.0rc2", max_attempts=1, delay_seconds=0.0)


def test_verify_published_fails_when_incomplete() -> None:
    with patch(
        "scripts.verify_pypi_publish.missing_packages",
        return_value=["myrm-agent-harness==0.1.0rc2"],
    ):
        try:
            verify_published("0.1.0rc2", max_attempts=1, delay_seconds=0.0)
        except SystemExit as exc:
            assert "incomplete" in str(exc).lower()
        else:
            raise AssertionError("expected SystemExit for incomplete PyPI publish")
