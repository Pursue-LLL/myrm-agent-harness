"""Unified facade suite for Cross-Harness Context State AST and lossless rehydration.

[INPUT]
- SessionStateAST instances, raw payloads, target harness formats, sandbox roots.

[OUTPUT]
- Unified APIs for serialization, hydration, hot-swap assessment, and artifact continuity.

[POS]
- Harness context management in agent/context_management/cross_harness_ast/cross_harness_suite.py.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Mapping, Sequence

from .artifact_continuity_gateway import ArtifactContinuityGateway
from .ast_types import (
    ArtifactContinuityReport,
    AstArtifactRef,
    AstMessageRole,
    AstToolInvocation,
    AstTurn,
    ContextHealthReport,
    HarnessHotSwapBadge,
    HarnessTargetFormat,
    SessionStateAST,
)
from .heterogeneous_hydration_bridge import HeterogeneousContextHydrationBridge
from .state_ast_engine import SessionStateASTEngine


class CrossHarnessSuite:
    """Orchestration facade for framework-agnostic session ASTs and zero-loss hot-swapping."""

    @classmethod
    def create_session_ast(
        cls,
        session_id: str,
        metadata: Mapping[str, str] | None = None,
    ) -> SessionStateAST:
        """Initializes a new empty canonical SessionStateAST container."""
        return SessionStateASTEngine.create_empty_ast(session_id=session_id, metadata=metadata)

    @classmethod
    def append_turn(
        cls,
        ast: SessionStateAST,
        role: AstMessageRole,
        text_content: str,
        thinking_trace: str | None = None,
        tool_invocations: Sequence[AstToolInvocation] = (),
        artifact_refs: Sequence[AstArtifactRef] = (),
        turn_id: str | None = None,
    ) -> SessionStateAST:
        """Appends a new conversation turn into the AST."""
        tid = turn_id or f"turn-{len(ast.turns)}"
        turn = SessionStateASTEngine.build_turn(
            turn_id=tid,
            role=role,
            text_content=text_content,
            thinking_trace=thinking_trace,
            tool_invocations=tool_invocations,
            artifact_refs=artifact_refs,
        )
        return SessionStateASTEngine.append_turn(ast, turn)

    @classmethod
    def serialize_to_harness(
        cls,
        ast: SessionStateAST,
        target_format: HarnessTargetFormat,
    ) -> Mapping[str, object]:
        """Translates canonical AST into the target harness's native serialization format."""
        return HeterogeneousContextHydrationBridge.serialize(ast, target_format)

    @classmethod
    def hydrate_from_harness(
        cls,
        payload: Mapping[str, object],
        source_format: HarnessTargetFormat,
    ) -> SessionStateAST:
        """Hydrates an alien harness payload into a canonical SessionStateAST."""
        return HeterogeneousContextHydrationBridge.hydrate(payload, source_format)

    @classmethod
    def assess_hot_swap_readiness(
        cls,
        ast: SessionStateAST,
        source_harness: HarnessTargetFormat,
        target_harness: HarnessTargetFormat,
        target_token_budget: int = 128000,
    ) -> tuple[ContextHealthReport, HarnessHotSwapBadge]:
        """Evaluates token window capacity and produces frontend hot-swap status badges."""
        estimated_tokens = SessionStateASTEngine.calculate_token_estimate(ast)
        turn_count = len(ast.turns)
        artifacts = SessionStateASTEngine.extract_all_artifact_refs(ast)

        is_compatible = estimated_tokens <= target_token_budget
        compression_recommended = estimated_tokens > int(target_token_budget * 0.85)

        remediation: str | None = None
        if not is_compatible:
            remediation = (
                f"Context size (~{estimated_tokens} tokens) exceeds target {target_harness.value} "
                f"window limit ({target_token_budget}). Please trigger semantic compaction before hot-swap."
            )
        elif compression_recommended:
            remediation = "Approaching 85% capacity threshold. Pruning or compacting idle turns is advised."

        health_report = ContextHealthReport(
            estimated_tokens=estimated_tokens,
            turn_count=turn_count,
            target_harness_limit=target_token_budget,
            is_compatible=is_compatible,
            compression_recommended=compression_recommended,
            actionable_remediation=remediation,
        )

        status_msg = (
            f"Ready to hot-swap from {source_harness.value} to {target_harness.value}. "
            f"Preserving {turn_count} turns and {len(artifacts)} sandbox artifacts."
            if is_compatible
            else f"Hot-swap blocked: Context exceeds target budget by {estimated_tokens - target_token_budget} tokens."
        )

        badge = HarnessHotSwapBadge(
            source_harness=source_harness,
            target_harness=target_harness,
            preserved_turns=turn_count,
            preserved_artifacts=len(artifacts),
            is_hot_swappable=is_compatible,
            status_message=status_msg,
        )

        return health_report, badge

    @classmethod
    def verify_artifact_continuity(
        cls,
        ast: SessionStateAST,
        sandbox_volume_root: str | Path,
    ) -> ArtifactContinuityReport:
        """Performs physical integrity verification of sandbox files attached to the AST."""
        return ArtifactContinuityGateway.verify_continuity(ast, sandbox_volume_root)

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
        """Registers a sandbox file into the AST with SHA-256 integrity seal."""
        return ArtifactContinuityGateway.attach_artifact(
            ast=ast,
            turn_id=turn_id,
            relative_file_path=relative_file_path,
            sandbox_volume_root=sandbox_volume_root,
            summary=summary,
            mime_type=mime_type,
        )


# Full canonical alias
CrossHarnessContextStateASTAndLosslessRehydrationSuite = CrossHarnessSuite
