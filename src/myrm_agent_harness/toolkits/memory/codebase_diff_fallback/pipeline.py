"""Pipeline for multi-tier codebase diff volume fallback.

Implements the four-tier adaptive diff funnel (Micro, Moderate, Large, Massive)
with hard truncation detection, lockfile noise filtration, and directory clustering.
"""

from __future__ import annotations

from collections import defaultdict

from .classifier import DiffPathClassifier
from .models import (
    DiffCategory,
    DiffFallbackVerdict,
    DiffFileEntry,
    DiffVolumeTier,
    DirectoryAggregate,
    LargeDiffFallbackConfig,
)


class LargeDiffFallbackPipeline:
    """Executes multi-tier analysis and safe summary generation for code diffs."""

    def __init__(self, config: LargeDiffFallbackConfig | None = None) -> None:
        self.config = config or LargeDiffFallbackConfig()

    def evaluate_tier(
        self,
        files: list[DiffFileEntry],
        declared_total_files: int | None = None,
        is_api_truncated: bool = False,
    ) -> tuple[DiffVolumeTier, bool, str | None]:
        """Determines the appropriate execution tier and truncation status."""
        total_files = len(files)
        total_changes = sum(f.total_changes for f in files)

        # 1. Truncation and hard cap guard (aligned with codebase-memory #2269)
        if is_api_truncated:
            return (
                DiffVolumeTier.MASSIVE,
                True,
                "API explicitly marked file list as truncated",
            )

        if declared_total_files is not None and declared_total_files > total_files:
            return (
                DiffVolumeTier.MASSIVE,
                True,
                f"File list truncated: received {total_files} of {declared_total_files} declared files",
            )

        if total_files >= self.config.hard_file_cap:
            return (
                DiffVolumeTier.MASSIVE,
                True,
                f"File list reached or exceeded hard cap of {self.config.hard_file_cap} files",
            )

        if declared_total_files is not None and declared_total_files >= self.config.hard_file_cap:
            return (
                DiffVolumeTier.MASSIVE,
                True,
                f"Declared file count {declared_total_files} reached hard cap",
            )

        # 2. Tier evaluation based on volume
        if (
            total_files <= self.config.micro_max_files
            and total_changes <= self.config.micro_max_lines
        ):
            return DiffVolumeTier.MICRO, False, None

        if (
            total_files <= self.config.moderate_max_files
            and total_changes <= self.config.moderate_max_lines
        ):
            return DiffVolumeTier.MODERATE, False, None

        if (
            total_files <= self.config.large_max_files
            and total_changes <= self.config.large_max_lines
        ):
            return DiffVolumeTier.LARGE, False, None

        return DiffVolumeTier.MASSIVE, False, None

    def process(
        self,
        raw_files: list[DiffFileEntry],
        declared_total_files: int | None = None,
        is_api_truncated: bool = False,
        commit_message: str | None = None,
    ) -> DiffFallbackVerdict:
        """Processes a diff payload through the appropriate tier pipeline."""
        # Enrich and classify each entry
        classified_files = [DiffPathClassifier.enrich_entry(f) for f in raw_files]

        tier, is_truncated, truncation_reason = self.evaluate_tier(
            classified_files,
            declared_total_files=declared_total_files,
            is_api_truncated=is_api_truncated,
        )

        total_add = sum(f.additions for f in classified_files)
        total_del = sum(f.deletions for f in classified_files)

        # Directory aggregations
        dir_aggregates = self._aggregate_by_directory(classified_files)

        applied_optimizations: list[str] = []
        if is_truncated:
            applied_optimizations.append("truncation_guard_activated")

        if tier == DiffVolumeTier.MICRO:
            return self._synthesize_micro(
                classified_files,
                total_add,
                total_del,
                dir_aggregates,
                commit_message,
                applied_optimizations,
            )
        elif tier == DiffVolumeTier.MODERATE:
            return self._synthesize_moderate(
                classified_files,
                total_add,
                total_del,
                dir_aggregates,
                commit_message,
                applied_optimizations,
            )
        elif tier == DiffVolumeTier.LARGE:
            return self._synthesize_large(
                classified_files,
                total_add,
                total_del,
                dir_aggregates,
                commit_message,
                applied_optimizations,
            )
        else:  # MASSIVE
            return self._synthesize_massive(
                classified_files,
                total_add,
                total_del,
                dir_aggregates,
                commit_message,
                is_truncated,
                truncation_reason,
                applied_optimizations,
            )

    def _aggregate_by_directory(
        self, files: list[DiffFileEntry]
    ) -> list[DirectoryAggregate]:
        """Groups file statistics by top directory."""
        grouped: dict[str, list[DiffFileEntry]] = defaultdict(list)
        for f in files:
            top_dir = DiffPathClassifier.extract_top_directory(f.path)
            grouped[top_dir].append(f)

        aggregates: list[DirectoryAggregate] = []
        for dir_name, dir_files in sorted(grouped.items(), key=lambda x: -len(x[1])):
            add_sum = sum(item.additions for item in dir_files)
            del_sum = sum(item.deletions for item in dir_files)
            # Find dominant category
            cat_counts: dict[DiffCategory, int] = defaultdict(int)
            for item in dir_files:
                cat_counts[item.category] += 1
            primary = max(cat_counts.items(), key=lambda x: x[1])[0]

            aggregates.append(
                DirectoryAggregate(
                    directory=dir_name,
                    file_count=len(dir_files),
                    total_additions=add_sum,
                    total_deletions=del_sum,
                    primary_category=primary,
                )
            )
        return aggregates

    def _synthesize_micro(
        self,
        files: list[DiffFileEntry],
        total_add: int,
        total_del: int,
        dir_aggregates: list[DirectoryAggregate],
        commit_message: str | None,
        optimizations: list[str],
    ) -> DiffFallbackVerdict:
        optimizations.append("full_fidelity_ast_retained")
        lines: list[str] = [
            f"[Diff Mode: MICRO] {len(files)} files changed (+{total_add}, -{total_del})"
        ]
        if commit_message:
            lines.append(f"Commit: {commit_message.strip()}")
        lines.append("Files:")
        for f in files:
            renamed_info = f" (from {f.old_path})" if f.is_renamed and f.old_path else ""
            lines.append(f"  - {f.path}{renamed_info} (+{f.additions}, -{f.deletions})")
            if f.patch_snippet:
                snippet = f.patch_snippet.strip()
                if len(snippet) > 400:
                    snippet = snippet[:400] + "... [truncated]"
                lines.append(f"    Patch: {snippet}")

        return DiffFallbackVerdict(
            tier=DiffVolumeTier.MICRO,
            total_files=len(files),
            total_additions=total_add,
            total_deletions=total_del,
            is_truncated=False,
            active_files_count=len(files),
            filtered_noise_files_count=0,
            directory_aggregates=dir_aggregates,
            summary_text="\n".join(lines),
            applied_optimizations=optimizations,
        )

    def _synthesize_moderate(
        self,
        files: list[DiffFileEntry],
        total_add: int,
        total_del: int,
        dir_aggregates: list[DirectoryAggregate],
        commit_message: str | None,
        optimizations: list[str],
    ) -> DiffFallbackVerdict:
        optimizations.append("noise_filtration_active")
        optimizations.append("patch_snippets_clipped")

        active_files: list[DiffFileEntry] = []
        noise_files: list[DiffFileEntry] = []

        for f in files:
            if f.category in {DiffCategory.LOCKFILE, DiffCategory.GENERATED, DiffCategory.ASSET_BINARY}:
                noise_files.append(f)
            else:
                active_files.append(f)

        lines: list[str] = [
            f"[Diff Mode: MODERATE] {len(files)} files changed (+{total_add}, -{total_del})"
        ]
        if commit_message:
            lines.append(f"Commit: {commit_message.strip()}")

        lines.append(f"Active Source Files ({len(active_files)}):")
        for f in active_files[:50]:
            lines.append(f"  - {f.path} (+{f.additions}, -{f.deletions})")
            if f.patch_snippet:
                snippet = f.patch_snippet.strip()[:150]
                lines.append(f"    Summary: {snippet}...")
        if len(active_files) > 50:
            lines.append(f"  ... and {len(active_files) - 50} more core files")

        if noise_files:
            noise_add = sum(n.additions for n in noise_files)
            noise_del = sum(n.deletions for n in noise_files)
            lines.append(
                f"Folded Noise/Generated Files ({len(noise_files)} files, +{noise_add}, -{noise_del}):"
            )
            for n in noise_files[:10]:
                lines.append(f"  - [{n.category.value}] {n.path}")
            if len(noise_files) > 10:
                lines.append(f"  ... and {len(noise_files) - 10} more non-core files")

        return DiffFallbackVerdict(
            tier=DiffVolumeTier.MODERATE,
            total_files=len(files),
            total_additions=total_add,
            total_deletions=total_del,
            is_truncated=False,
            active_files_count=len(active_files),
            filtered_noise_files_count=len(noise_files),
            directory_aggregates=dir_aggregates,
            summary_text="\n".join(lines),
            applied_optimizations=optimizations,
        )

    def _synthesize_large(
        self,
        files: list[DiffFileEntry],
        total_add: int,
        total_del: int,
        dir_aggregates: list[DirectoryAggregate],
        commit_message: str | None,
        optimizations: list[str],
    ) -> DiffFallbackVerdict:
        optimizations.append("directory_level_clustering")
        optimizations.append("top_components_extracted")
        optimizations.append("raw_patches_omitted")

        # Top 20 modified files by line count
        top_files = sorted(files, key=lambda x: -x.total_changes)[:20]

        lines: list[str] = [
            f"[Diff Mode: LARGE] Architecture Summary: {len(files)} files changed (+{total_add}, -{total_del})"
        ]
        if commit_message:
            lines.append(f"Commit: {commit_message.strip()}")

        lines.append("Module Clusters:")
        for aggr in dir_aggregates[:10]:
            lines.append(
                f"  - {aggr.directory}/: {aggr.file_count} files (+{aggr.total_additions}, -{aggr.total_deletions}) [{aggr.primary_category.value}]"
            )

        lines.append("Top Impacted Files:")
        for f in top_files:
            lines.append(f"  - {f.path} (+{f.additions}, -{f.deletions}) [{f.category.value}]")

        return DiffFallbackVerdict(
            tier=DiffVolumeTier.LARGE,
            total_files=len(files),
            total_additions=total_add,
            total_deletions=total_del,
            is_truncated=False,
            active_files_count=len(top_files),
            filtered_noise_files_count=len(files) - len(top_files),
            directory_aggregates=dir_aggregates,
            summary_text="\n".join(lines),
            applied_optimizations=optimizations,
        )

    def _synthesize_massive(
        self,
        files: list[DiffFileEntry],
        total_add: int,
        total_del: int,
        dir_aggregates: list[DirectoryAggregate],
        commit_message: str | None,
        is_truncated: bool,
        truncation_reason: str | None,
        optimizations: list[str],
    ) -> DiffFallbackVerdict:
        optimizations.append("massive_fallback_fail_safe")
        optimizations.append("zero_ast_token_shield")

        lines: list[str] = [
            f"[Diff Mode: MASSIVE] Fail-Safe Topology Summary: {len(files)} files (+{total_add}, -{total_del})"
        ]
        if is_truncated:
            lines.append(f"⚠️ Truncation Warning: {truncation_reason or 'Diff truncated'}")
        if commit_message:
            lines.append(f"Commit Intent: {commit_message.strip()}")

        lines.append("Subsystem Distribution:")
        for aggr in dir_aggregates[:15]:
            lines.append(
                f"  - {aggr.directory}/: {aggr.file_count} files (+{aggr.total_additions}, -{aggr.total_deletions})"
            )

        return DiffFallbackVerdict(
            tier=DiffVolumeTier.MASSIVE,
            total_files=len(files),
            total_additions=total_add,
            total_deletions=total_del,
            is_truncated=is_truncated,
            truncation_reason=truncation_reason,
            active_files_count=0,
            filtered_noise_files_count=len(files),
            directory_aggregates=dir_aggregates,
            summary_text="\n".join(lines),
            applied_optimizations=optimizations,
        )
