"""High-performance pre-injection ground truth drift detector.

Performs sub-5ms physical presence and symbol verification against the active
workspace to intercept obsolete memories and prevent hallucinations.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.drift_defense.reference_extractor::GroundTruthReferenceExtractor (POS: Zero-LLM fast
  regular expression extractor for file paths and code symbols.)
- toolkits.memory.drift_defense.types::DriftCheckRequest, DriftCheckResult, DriftDefenseConfig, DriftType,
  MemoryDriftFinding (POS: Type definitions for ground truth priority and memory drift stale defense.)

[OUTPUT]
- GroundTruthDriftDetector: Detects physical file, configuration, and symbol drift before memory injection.

[POS]
High-performance pre-injection ground truth drift detector.
"""

from __future__ import annotations

import ast
import logging
import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory.drift_defense.reference_extractor import (
    GroundTruthReferenceExtractor,
)
from myrm_agent_harness.toolkits.memory.drift_defense.types import (
    DriftCheckRequest,
    DriftCheckResult,
    DriftDefenseConfig,
    DriftType,
    MemoryDriftFinding,
)

logger = logging.getLogger(__name__)


class GroundTruthDriftDetector:
    """Detects physical file, configuration, and symbol drift before memory injection."""

    def __init__(
        self,
        config: DriftDefenseConfig | None = None,
        extractor: GroundTruthReferenceExtractor | None = None,
    ) -> None:
        self.config = config or DriftDefenseConfig()
        self.extractor = extractor or GroundTruthReferenceExtractor()
        # Fast memory cache: path_str -> (mtime, exists, symbols_set, expires_at)
        self._cache: dict[str, tuple[float, bool, set[str], float]] = {}

    def check(self, request: DriftCheckRequest) -> DriftCheckResult:
        """Evaluate memory candidate against current physical workspace state."""
        if not self.config.enabled:
            return DriftCheckResult(
                memory_id=request.memory_id,
                is_drifted=False,
                confidence_penalty=0.0,
                findings=[],
                decorated_content=request.content,
            )

        workspace = Path(request.workspace_root).resolve()
        findings: list[MemoryDriftFinding] = []

        # 1. Evaluate explicit recorded path if provided
        if request.recorded_path:
            file_findings = self._check_path_and_symbol(
                workspace=workspace,
                rel_path=request.recorded_path,
                expected_symbol=request.recorded_symbol,
            )
            findings.extend(file_findings)

        # 2. Extract references from content text
        extracted_refs = self.extractor.extract(request.content)
        for ref in extracted_refs:
            if ref.kind == "file_path":
                # Only check if path looks intended for local project
                target_path = workspace / ref.target
                if not target_path.exists() and self._is_likely_project_file(ref.target):
                    findings.append(
                        MemoryDriftFinding(
                            drift_type=DriftType.FILE_NOT_FOUND,
                            reference_target=ref.target,
                            detail=f"Referenced file '{ref.target}' does not exist in active workspace.",
                        )
                    )

        is_drifted = bool(findings)
        penalty = self.config.stale_confidence_penalty if is_drifted else 0.0

        # Construct decorated text
        if is_drifted:
            decorated = self.config.stale_warning_template.format(content=request.content)
        else:
            decorated = request.content

        return DriftCheckResult(
            memory_id=request.memory_id,
            is_drifted=is_drifted,
            confidence_penalty=penalty,
            findings=findings,
            decorated_content=decorated,
        )

    def _check_path_and_symbol(
        self,
        workspace: Path,
        rel_path: str,
        expected_symbol: str | None,
    ) -> list[MemoryDriftFinding]:
        findings: list[MemoryDriftFinding] = []
        target_path = (workspace / rel_path).resolve()

        if not target_path.exists():
            findings.append(
                MemoryDriftFinding(
                    drift_type=DriftType.FILE_NOT_FOUND,
                    reference_target=rel_path,
                    detail=f"Bound file '{rel_path}' is missing or deleted from repository.",
                )
            )
            return findings

        if expected_symbol:
            symbols = self._get_cached_symbols(target_path)
            if expected_symbol not in symbols:
                findings.append(
                    MemoryDriftFinding(
                        drift_type=DriftType.SYMBOL_NOT_FOUND,
                        reference_target=f"{rel_path}::{expected_symbol}",
                        detail=(
                            f"Bound symbol '{expected_symbol}' is no longer found in '{rel_path}'."
                        ),
                    )
                )

        return findings

    def _get_cached_symbols(self, file_path: Path) -> set[str]:
        cache_key = str(file_path)
        now = time.time()
        try:
            stat = file_path.stat()
            current_mtime = stat.st_mtime
        except OSError:
            return set()

        cached = self._cache.get(cache_key)
        if cached:
            mtime, exists, symbols, expires_at = cached
            if exists and mtime == current_mtime and now < expires_at:
                return symbols

        # Parse AST symbols
        symbols_found: set[str] = set()
        if file_path.suffix == ".py":
            try:
                code_text = file_path.read_text(encoding="utf-8")
                tree = ast.parse(code_text)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        symbols_found.add(node.name)
            except Exception as exc:
                logger.debug("Failed AST parsing for %s: %s", file_path, exc)

        expires_at = now + self.config.cache_ttl_seconds
        self._cache[cache_key] = (current_mtime, True, symbols_found, expires_at)
        return symbols_found

    @staticmethod
    def _is_likely_project_file(path_str: str) -> bool:
        # Avoid checking general system files or top-level generic terms
        clean = path_str.lower()
        if clean.startswith(("/", "http", "https")):
            return False
        return any(
            clean.endswith(ext)
            for ext in (".py", ".ts", ".js", ".json", ".yaml", ".yml", ".toml", ".sql", ".sh")
        )
