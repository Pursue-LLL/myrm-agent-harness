"""Session state AST engine for creation, manipulation, validation, and metrics.

[INPUT]
- Raw turn data, messages, session metadata, or existing SessionStateAST instances.

[OUTPUT]
- Validated SessionStateAST objects, integrity reports, token estimations,
  and aggregated artifact reference sequences.

[POS]
- Harness context management in agent/context_management/cross_harness_ast/state_ast_engine.py.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence

from .ast_types import (
    AstArtifactRef,
    AstContentBlock,
    AstMessageRole,
    AstToolInvocation,
    AstTurn,
    SessionStateAST,
)


class SessionStateASTEngine:
    """Core builder and analyzer for framework-agnostic session state ASTs."""

    @classmethod
    def create_empty_ast(
        cls,
        session_id: str,
        metadata: Mapping[str, str] | None = None,
    ) -> SessionStateAST:
        """Instantiates an empty SessionStateAST container."""
        now_ms = int(time.time() * 1000)
        return SessionStateAST(
            session_id=session_id,
            created_at_ms=now_ms,
            turns=(),
            session_metadata=dict(metadata or {}),
            version="1.0.0",
        )

    @classmethod
    def build_turn(
        cls,
        turn_id: str,
        role: AstMessageRole,
        text_content: str,
        thinking_trace: str | None = None,
        tool_invocations: Sequence[AstToolInvocation] = (),
        artifact_refs: Sequence[AstArtifactRef] = (),
        timestamp_ms: int | None = None,
    ) -> AstTurn:
        """Constructs an individual AstTurn with standard content blocks."""
        blocks: list[AstContentBlock] = [
            AstContentBlock(block_type="text", content=text_content)
        ]
        if thinking_trace:
            blocks.append(
                AstContentBlock(block_type="thinking", content=thinking_trace)
            )

        now_ms = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        return AstTurn(
            turn_id=turn_id,
            role=role,
            content_blocks=tuple(blocks),
            thinking_trace=thinking_trace,
            tool_invocations=tuple(tool_invocations),
            artifact_refs=tuple(artifact_refs),
            timestamp_ms=now_ms,
        )

    @classmethod
    def append_turn(cls, ast: SessionStateAST, turn: AstTurn) -> SessionStateAST:
        """Returns a new immutable SessionStateAST with the provided turn appended."""
        new_turns = list(ast.turns)
        new_turns.append(turn)
        return SessionStateAST(
            session_id=ast.session_id,
            created_at_ms=ast.created_at_ms,
            turns=tuple(new_turns),
            session_metadata=ast.session_metadata,
            version=ast.version,
        )

    @classmethod
    def calculate_token_estimate(cls, ast: SessionStateAST) -> int:
        """Heuristically estimates token consumption across all turns and blocks."""
        total_chars = 0
        for turn in ast.turns:
            for block in turn.content_blocks:
                total_chars += len(block.content)
            for tool_call in turn.tool_invocations:
                total_chars += len(tool_call.tool_name) + len(tool_call.result_output)
                for k, v in tool_call.arguments.items():
                    total_chars += len(k) + len(v)
            for artifact in turn.artifact_refs:
                total_chars += len(artifact.file_path) + len(artifact.summary)

        # Standard heuristic: ~3.8 chars per token + structural overhead per turn
        estimated = int(total_chars / 3.8) + (len(ast.turns) * 4)
        return max(estimated, 0)

    @classmethod
    def validate_ast_integrity(cls, ast: SessionStateAST) -> Sequence[str]:
        """Validates that turn identifiers are unique and essential fields are coherent."""
        errors: list[str] = []
        if not ast.session_id.strip():
            errors.append("SessionStateAST session_id must not be empty.")

        seen_turn_ids: set[str] = set()
        for idx, turn in enumerate(ast.turns):
            if not turn.turn_id.strip():
                errors.append(f"Turn at index {idx} has an empty turn_id.")
            elif turn.turn_id in seen_turn_ids:
                errors.append(f"Duplicate turn_id detected: '{turn.turn_id}' at index {idx}.")
            seen_turn_ids.add(turn.turn_id)

            if not turn.content_blocks and not turn.tool_invocations:
                errors.append(f"Turn '{turn.turn_id}' has neither content blocks nor tool invocations.")

        return tuple(errors)

    @classmethod
    def extract_all_artifact_refs(cls, ast: SessionStateAST) -> Sequence[AstArtifactRef]:
        """Aggregates and deduplicates all artifact references created across the session."""
        refs_by_id: dict[str, AstArtifactRef] = {}
        for turn in ast.turns:
            for ref in turn.artifact_refs:
                if ref.artifact_id not in refs_by_id:
                    refs_by_id[ref.artifact_id] = ref
        return tuple(refs_by_id.values())
