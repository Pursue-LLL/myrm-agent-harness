"""Artifact continuity gateway assuring persistent sandbox pointer integrity.

[INPUT]
- SessionStateAST instances, sandbox volume root paths, artifact definitions.

[OUTPUT]
- ArtifactContinuityReport assessing cross-harness file presence and cryptographic digest match.
- Augmented SessionStateAST with freshly registered artifact pointers.

[POS]
- Harness context management in agent/context_management/cross_harness_ast/artifact_continuity_gateway.py.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Sequence

from .ast_types import (
    ArtifactContinuityReport,
    AstArtifactRef,
    AstTurn,
    SessionStateAST,
)
from .state_ast_engine import SessionStateASTEngine


class ArtifactContinuityGateway:
    """Verifies and maintains persistent sandbox artifact continuity across harness switches."""

    @classmethod
    def verify_continuity(
        cls,
        ast: SessionStateAST,
        sandbox_volume_root: str | Path,
    ) -> ArtifactContinuityReport:
        """Physical integrity check validating that artifacts exist and match cryptographic hashes."""
        root = Path(sandbox_volume_root)
        all_artifacts = SessionStateASTEngine.extract_all_artifact_refs(ast)

        if not all_artifacts:
            return ArtifactContinuityReport(
                total_artifacts=0,
                verified_count=0,
                missing_paths=(),
                hash_mismatches=(),
                is_fully_continuous=True,
            )

        missing: list[str] = []
        mismatched: list[str] = []
        verified_count = 0

        for art in all_artifacts:
            # Resolve physical target inside sandbox
            target_file = root / art.file_path.lstrip("/\\")
            if not target_file.is_file():
                missing.append(art.file_path)
                continue

            try:
                content = target_file.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                if art.sha256_digest and digest.lower() != art.sha256_digest.lower():
                    mismatched.append(f"{art.file_path} (expected {art.sha256_digest[:8]}, got {digest[:8]})")
                else:
                    verified_count += 1
            except Exception:
                missing.append(art.file_path)

        is_continuous = len(missing) == 0 and len(mismatched) == 0
        return ArtifactContinuityReport(
            total_artifacts=len(all_artifacts),
            verified_count=verified_count,
            missing_paths=tuple(missing),
            hash_mismatches=tuple(mismatched),
            is_fully_continuous=is_continuous,
        )

    @classmethod
    def attach_artifact(
        cls,
        ast: SessionStateAST,
        turn_id: str,
        relative_file_path: str,
        sandbox_volume_root: str | Path,
        summary: str,
        mime_type: str = "text/plain",
    ) -> tuple[SessionStateAST, AstArtifactRef]:
        """Calculates hash for a sandbox file and injects an AstArtifactRef into the specified turn."""
        root = Path(sandbox_volume_root)
        target = root / relative_file_path.lstrip("/\\")
        digest = ""
        if target.is_file():
            digest = hashlib.sha256(target.read_bytes()).hexdigest()

        art_id = f"art-{uuid.uuid4().hex[:8]}"
        ref = AstArtifactRef(
            artifact_id=art_id,
            file_path=relative_file_path,
            mime_type=mime_type,
            sha256_digest=digest,
            summary=summary,
            created_turn_id=turn_id,
        )

        new_turns: list[AstTurn] = []
        turn_found = False
        for t in ast.turns:
            if t.turn_id == turn_id:
                turn_found = True
                augmented_refs = list(t.artifact_refs)
                augmented_refs.append(ref)
                new_turns.append(
                    AstTurn(
                        turn_id=t.turn_id,
                        role=t.role,
                        content_blocks=t.content_blocks,
                        thinking_trace=t.thinking_trace,
                        tool_invocations=t.tool_invocations,
                        artifact_refs=tuple(augmented_refs),
                        timestamp_ms=t.timestamp_ms,
                    )
                )
            else:
                new_turns.append(t)

        if not turn_found and new_turns:
            # Fallback attach to the latest turn
            last = new_turns[-1]
            augmented = list(last.artifact_refs)
            augmented.append(ref)
            new_turns[-1] = AstTurn(
                turn_id=last.turn_id,
                role=last.role,
                content_blocks=last.content_blocks,
                thinking_trace=last.thinking_trace,
                tool_invocations=last.tool_invocations,
                artifact_refs=tuple(augmented),
                timestamp_ms=last.timestamp_ms,
            )

        updated_ast = SessionStateAST(
            session_id=ast.session_id,
            created_at_ms=ast.created_at_ms,
            turns=tuple(new_turns),
            session_metadata=ast.session_metadata,
            version=ast.version,
        )
        return updated_ast, ref
