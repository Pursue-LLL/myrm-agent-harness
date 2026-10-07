"""Atomic cross-file diff applier with two-phase verification and rollback.

Ensures that multi-file refactoring diffs apply cleanly across all targets
or roll back completely to maintain repository consistency.

[INPUT]
- runtime.context.full_repo_attention_anchor::AstDriftToleranceAligner (POS: Attention anchor injection and
  AST drift tolerance aligner for 1M context.)
- runtime.context.full_repo_refactor_types::RefactorApplyResult, RefactorPlanBundle (POS: Type definitions
  for native 1M long-context full-repo refactoring pipeline.)

[OUTPUT]
- CrossFileDiffAtomicApplier: Applies multi-file refactoring diffs atomically with strict verification.

[POS]
Atomic cross-file diff applier with two-phase verification and rollback.
"""

import hashlib
import os

from myrm_agent_harness.runtime.context.full_repo_attention_anchor import (
    AstDriftToleranceAligner,
)
from myrm_agent_harness.runtime.context.full_repo_refactor_types import (
    RefactorApplyResult,
    RefactorPlanBundle,
)


class CrossFileDiffAtomicApplier:
    """Applies multi-file refactoring diffs atomically with strict verification."""

    def __init__(
        self,
        aligner: AstDriftToleranceAligner | None = None,
    ) -> None:
        self._aligner = aligner or AstDriftToleranceAligner()

    def apply_plan(
        self,
        repo_root: str,
        plan: RefactorPlanBundle,
    ) -> RefactorApplyResult:
        """Execute atomic multi-file refactor transaction across repo_root."""
        if not plan.diffs:
            return RefactorApplyResult(
                success=True,
                applied_files=[],
                rolled_back_files=[],
                error_message=None,
                updated_file_hashes={},
            )

        # ----------------------------------------------------
        # Phase 1: Pre-flight Verification & In-Memory Compute
        # ----------------------------------------------------
        simulated_contents: dict[str, str] = {}
        original_contents: dict[str, str | None] = {}
        created_files: set[str] = set()

        for diff in plan.diffs:
            abs_path = os.path.join(repo_root, diff.file_path)
            file_exists = os.path.exists(abs_path)

            if diff.file_path not in simulated_contents:
                if file_exists:
                    try:
                        with open(abs_path, encoding="utf-8") as f:
                            cur_content = f.read()
                        original_contents[diff.file_path] = cur_content
                    except OSError as err:
                        return RefactorApplyResult(
                            success=False,
                            error_message=f"Read failure on `{diff.file_path}`: {err}",
                        )
                else:
                    original_contents[diff.file_path] = None
                    created_files.add(diff.file_path)
                    cur_content = ""
                simulated_contents[diff.file_path] = cur_content
            else:
                cur_content = simulated_contents[diff.file_path]

            # Verify base hash if specified and file exists
            if diff.expected_base_hash and file_exists:
                actual_hash = hashlib.sha256(
                    original_contents[diff.file_path].encode("utf-8")  # type: ignore[union-attr]
                ).hexdigest()
                if actual_hash != diff.expected_base_hash:
                    return RefactorApplyResult(
                        success=False,
                        error_message=(
                            f"Base hash mismatch on `{diff.file_path}`: "
                            f"expected {diff.expected_base_hash[:8]}, "
                            f"got {actual_hash[:8]}"
                        ),
                    )

            # Check target snippet & apply substitution in-memory
            if not diff.target_snippet and not file_exists:
                # Direct file creation
                simulated_contents[diff.file_path] = diff.replacement_snippet
            else:
                slice_res = self._aligner.find_target_slice(
                    full_content=cur_content,
                    target_snippet=diff.target_snippet,
                    line_hint=diff.line_hint,
                    symbol_anchor_name=diff.symbol_anchor_name,
                )
                if slice_res is None:
                    return RefactorApplyResult(
                        success=False,
                        error_message=(
                            f"Failed to locate target snippet in `{diff.file_path}` "
                            f"(symbol={diff.symbol_anchor_name}, hint={diff.line_hint})"
                        ),
                    )
                start_c, end_c = slice_res
                new_content = (
                    cur_content[:start_c]
                    + diff.replacement_snippet
                    + cur_content[end_c:]
                )
                simulated_contents[diff.file_path] = new_content

        # ----------------------------------------------------
        # Phase 2: Atomic Disk Application with Rollback
        # ----------------------------------------------------
        applied_paths: list[str] = []
        updated_hashes: dict[str, str] = {}

        for rel_path, new_text in simulated_contents.items():
            abs_path = os.path.join(repo_root, rel_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            try:
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(new_text)
                applied_paths.append(rel_path)
                updated_hashes[rel_path] = hashlib.sha256(
                    new_text.encode("utf-8")
                ).hexdigest()
            except OSError as io_err:
                # Immediate full rollback of all modified/created files
                rolled_back = self._rollback(
                    repo_root, original_contents, applied_paths, created_files
                )
                return RefactorApplyResult(
                    success=False,
                    applied_files=[],
                    rolled_back_files=rolled_back,
                    error_message=f"I/O error applying `{rel_path}`: {io_err}. Rolled back.",
                )

        return RefactorApplyResult(
            success=True,
            applied_files=applied_paths,
            rolled_back_files=[],
            error_message=None,
            updated_file_hashes=updated_hashes,
        )

    def _rollback(
        self,
        repo_root: str,
        original_contents: dict[str, str | None],
        applied_paths: list[str],
        created_files: set[str],
    ) -> list[str]:
        """Restore all modified files to original state and remove created ones."""
        rolled_back: list[str] = []
        for rel_path in applied_paths:
            abs_path = os.path.join(repo_root, rel_path)
            orig = original_contents.get(rel_path)
            try:
                if rel_path in created_files or orig is None:
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                else:
                    with open(abs_path, "w", encoding="utf-8") as f:
                        f.write(orig)
                rolled_back.append(rel_path)
            except OSError:
                pass
        return rolled_back
