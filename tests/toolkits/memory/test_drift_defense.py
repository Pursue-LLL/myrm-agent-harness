# [POS]: tests/toolkits/memory/test_drift_defense.py
# [INPUT]: pytest, myrm_agent_harness.toolkits.memory.drift_defense
# [OUTPUT]: test_drift_defense suite
"""Unit test suite for ground truth priority and memory drift defense.

Validates regex reference extraction, workspace existence/AST symbol checks,
sub-5ms caching, and prompt decoration under code drift conditions.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.drift_defense import (
    DriftCheckRequest,
    DriftDefenseConfig,
    DriftType,
    GroundTruthDriftDetector,
    GroundTruthReferenceExtractor,
    StaleMemoryDecorator,
)


@pytest.fixture
def workspace_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        # Create mock project files
        src_dir = ws / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        py_file = src_dir / "auth_service.py"
        py_file.write_text(
            "class AuthService:\n"
            "    def authenticate_user(self, username: str) -> bool:\n"
            "        return True\n",
            encoding="utf-8",
        )
        yield ws


def test_reference_extractor() -> None:
    extractor = GroundTruthReferenceExtractor()
    content = (
        "In src/auth_service.py we have class AuthService and function "
        "def authenticate_user using configuration DATABASE_URL."
    )
    refs = extractor.extract(content)
    targets = {r.target: r.kind for r in refs}

    assert "src/auth_service.py" in targets
    assert targets["src/auth_service.py"] == "file_path"
    assert "AuthService" in targets
    assert targets["AuthService"] == "symbol"
    assert "authenticate_user" in targets
    assert targets["authenticate_user"] == "symbol"
    assert "DATABASE_URL" in targets
    assert targets["DATABASE_URL"] == "config_key"


def test_drift_detector_pristine_memory(workspace_dir: Path) -> None:
    detector = GroundTruthDriftDetector()
    req = DriftCheckRequest(
        memory_id="mem-pristine",
        content="Use src/auth_service.py to verify credentials.",
        workspace_root=workspace_dir,
        recorded_path="src/auth_service.py",
        recorded_symbol="AuthService",
    )
    result = detector.check(req)

    assert result.is_drifted is False
    assert result.confidence_penalty == 0.0
    assert len(result.findings) == 0
    assert result.decorated_content == req.content
    assert "[⚠️ 过时警告" not in result.decorated_content


def test_drift_detector_missing_file(workspace_dir: Path) -> None:
    detector = GroundTruthDriftDetector()
    req = DriftCheckRequest(
        memory_id="mem-missing-file",
        content="Consult legacy_module.py for ancient routing guidelines.",
        workspace_root=workspace_dir,
        recorded_path="legacy_module.py",
    )
    result = detector.check(req)

    assert result.is_drifted is True
    assert result.confidence_penalty == 0.6
    assert len(result.findings) >= 1
    assert any(f.drift_type == DriftType.FILE_NOT_FOUND for f in result.findings)
    assert "[⚠️ 过时警告" in result.decorated_content


def test_drift_detector_missing_symbol(workspace_dir: Path) -> None:
    detector = GroundTruthDriftDetector()
    # auth_service.py exists, but OldDeprecatedClass does not
    req = DriftCheckRequest(
        memory_id="mem-missing-symbol",
        content="Instantiate OldDeprecatedClass inside auth service.",
        workspace_root=workspace_dir,
        recorded_path="src/auth_service.py",
        recorded_symbol="OldDeprecatedClass",
    )
    result = detector.check(req)

    assert result.is_drifted is True
    assert result.confidence_penalty == 0.6
    assert len(result.findings) >= 1
    assert any(f.drift_type == DriftType.SYMBOL_NOT_FOUND for f in result.findings)
    assert "[⚠️ 过时警告" in result.decorated_content


def test_drift_detector_fast_cache(workspace_dir: Path) -> None:
    detector = GroundTruthDriftDetector()
    req = DriftCheckRequest(
        memory_id="mem-bench",
        content="Check src/auth_service.py class AuthService.",
        workspace_root=workspace_dir,
        recorded_path="src/auth_service.py",
        recorded_symbol="AuthService",
    )

    # First pass warms cache
    detector.check(req)

    # Second pass benchmarks cached lookup (< 5ms)
    t0 = time.perf_counter()
    res = detector.check(req)
    duration_ms = (time.perf_counter() - t0) * 1000

    assert res.is_drifted is False
    assert duration_ms < 5.0, f"Cache lookup took {duration_ms:.2f}ms, expected < 5ms"


def test_stale_memory_decorator() -> None:
    config = DriftDefenseConfig(stale_confidence_penalty=0.4)
    decorator = StaleMemoryDecorator(config=config)

    # Test decoration
    decorated = decorator.decorate("Raw content", is_drifted=True)
    assert "[⚠️ 过时警告" in decorated
    assert "Raw content" in decorated

    unmodified = decorator.decorate("Raw content", is_drifted=False)
    assert unmodified == "Raw content"

    # Test confidence calculation
    from myrm_agent_harness.toolkits.memory.drift_defense.types import DriftCheckResult

    mock_result_drifted = DriftCheckResult(
        memory_id="m1",
        is_drifted=True,
        confidence_penalty=0.4,
        findings=[],
        decorated_content=decorated,
    )
    mock_result_clean = DriftCheckResult(
        memory_id="m2",
        is_drifted=False,
        confidence_penalty=0.0,
        findings=[],
        decorated_content="Raw content",
    )

    conf1 = decorator.compute_effective_confidence(0.9, mock_result_drifted)
    assert pytest.approx(conf1, 0.01) == 0.5

    conf2 = decorator.compute_effective_confidence(0.9, mock_result_clean)
    assert pytest.approx(conf2, 0.01) == 0.9

    # Floor at 0.0
    conf3 = decorator.compute_effective_confidence(0.2, mock_result_drifted)
    assert conf3 == 0.0
