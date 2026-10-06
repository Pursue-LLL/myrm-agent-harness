"""Native 1M long-context full-repo refactoring pipeline facade.

Coordinates full-repo AST packing, Lost-in-the-Middle attention anchoring,
and atomic two-phase cross-file refactor transaction execution.
"""

import os

from myrm_agent_harness.runtime.context.cross_file_diff_applier import (
    CrossFileDiffAtomicApplier,
)
from myrm_agent_harness.runtime.context.full_repo_ast_packer import (
    FullRepoAstPacker,
)
from myrm_agent_harness.runtime.context.full_repo_attention_anchor import (
    AttentionAnchorInjector,
)
from myrm_agent_harness.runtime.context.full_repo_refactor_types import (
    PackedRepoContext,
    RefactorApplyResult,
    RefactorPlanBundle,
    SemanticAnchor,
)


class NativeMillionTokenFullRepoRefactorPipeline:
    """End-to-end pipeline for 1M-token codebase packing and atomic refactoring."""

    def __init__(
        self,
        packer: FullRepoAstPacker | None = None,
        anchor_injector: AttentionAnchorInjector | None = None,
        diff_applier: CrossFileDiffAtomicApplier | None = None,
    ) -> None:
        self._packer = packer or FullRepoAstPacker()
        self._anchor_injector = anchor_injector or AttentionAnchorInjector()
        self._diff_applier = diff_applier or CrossFileDiffAtomicApplier()

    def pack_repo_for_refactor(
        self,
        repo_root: str,
        max_tokens: int = 1_000_000,
    ) -> PackedRepoContext:
        """Analyze repository AST, extract anchors, and pack files into 1M context."""
        topology = self._packer.scan_and_analyze(repo_root)
        outline = self._packer.generate_topology_outline(topology)
        anchors: list[SemanticAnchor] = (
            self._anchor_injector.extract_semantic_anchors(topology)
        )
        anchors_block = self._anchor_injector.render_anchors_block(anchors)

        structured_files: dict[str, str] = {}
        file_hashes: dict[str, str] = {}
        prompt_sections: list[str] = [
            "# REPOSITORY WIDE-CONTEXT REFACTORING ENVIRONMENT",
            "This context contains the complete source code, AST topology, and dependency structure.",
            outline,
        ]

        if anchors_block:
            prompt_sections.append(anchors_block)

        prompt_sections.append("## REPOSITORY SOURCE CODE FILES")

        accumulated_tokens = topology.estimated_total_tokens + len(outline) // 4
        # Sort files prioritizing those with dependents first, then alphabetically
        sorted_files = sorted(
            topology.file_nodes.keys(),
            key=lambda p: (
                -len(topology.cross_file_dependencies.get(p, set())),
                p,
            ),
        )

        for rel_path in sorted_files:
            node = topology.file_nodes[rel_path]
            abs_path = os.path.join(repo_root, rel_path)
            try:
                with open(abs_path, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue

            file_hashes[rel_path] = node.content_hash
            structured_files[rel_path] = content

            file_block = (
                f'<file path="{rel_path}" lines="{node.lines_count}" '
                f'sha256="{node.content_hash}">\n'
                f"{content}\n"
                f"</file>"
            )
            prompt_sections.append(file_block)

            # Check token budget safety ceiling
            if accumulated_tokens > max_tokens:
                break

        full_packed_prompt = "\n\n".join(prompt_sections)
        total_tokens = max(1, len(full_packed_prompt) // 4)

        return PackedRepoContext(
            header_topology_outline=outline,
            semantic_anchors=anchors,
            structured_files=structured_files,
            full_packed_prompt=full_packed_prompt,
            total_estimated_tokens=total_tokens,
            file_hashes=file_hashes,
        )

    def apply_refactor(
        self,
        repo_root: str,
        plan: RefactorPlanBundle,
    ) -> RefactorApplyResult:
        """Apply coordinated multi-file refactor transaction atomically."""
        return self._diff_applier.apply_plan(repo_root, plan)
