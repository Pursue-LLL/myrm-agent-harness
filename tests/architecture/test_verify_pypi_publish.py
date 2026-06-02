"""Architecture tests for post-upload PyPI verification."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.verify_pypi_publish import (  # noqa: E402
    _expected_packages,
    missing_packages,
    verify_published,
)


def test_expected_packages_count() -> None:
    assert len(_expected_packages()) == 7


def test_missing_packages_reports_all_absent() -> None:
    with patch("scripts.verify_pypi_publish._pypi_exists", return_value=False):
        missing = missing_packages("0.1.0rc1")
    assert len(missing) == 7
    assert missing[0] == "myrm-agent-harness==0.1.0rc1"


def test_verify_published_succeeds_when_complete() -> None:
    with patch("scripts.verify_pypi_publish.missing_packages", return_value=[]):
        verify_published("0.1.0rc1", max_attempts=1, delay_seconds=0.0)


def test_verify_published_fails_when_incomplete() -> None:
    with patch(
        "scripts.verify_pypi_publish.missing_packages",
        return_value=["myrm-agent-harness==0.1.0rc1"],
    ):
        try:
            verify_published("0.1.0rc1", max_attempts=1, delay_seconds=0.0)
        except SystemExit as exc:
            assert "incomplete" in str(exc).lower()
        else:
            raise AssertionError("expected SystemExit for incomplete PyPI publish")
