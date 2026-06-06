"""Architecture tests for post-upload PyPI verification."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.verify_pypi_publish import (
    _expected_packages,
    missing_packages,
    verify_published,
)


def test_expected_packages_count() -> None:
    assert len(_expected_packages()) == 7


def test_missing_packages_reports_all_absent() -> None:
    with (
        patch("scripts.verify_pypi_publish._pypi_exists", return_value=False),
        patch("scripts.verify_pypi_publish._release_has_compiled_core_extra", return_value=False),
    ):
        missing = missing_packages("0.1.0rc2")
    assert len(missing) == 8
    assert missing[0] == "myrm-agent-harness==0.1.0rc2"


def test_release_extra_missing_is_reported() -> None:
    with (
        patch("scripts.verify_pypi_publish._pypi_exists", return_value=True),
        patch("scripts.verify_pypi_publish._release_has_compiled_core_extra", return_value=False),
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
