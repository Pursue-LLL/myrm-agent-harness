"""Unified public facade for codebase diff fallback suite.

Provides a consolidated API for evaluating diff tiers, classifying files,
and producing safe, noise-filtered summaries for codebase memory ingestion.
"""

from __future__ import annotations

from .classifier import DiffPathClassifier
from .models import (
    DiffCategory,
    DiffFallbackVerdict,
    DiffFileEntry,
    DiffVolumeTier,
    LargeDiffFallbackConfig,
)
from .pipeline import LargeDiffFallbackPipeline


class CodebaseDiffFallbackSuite:
    """Unified entry point for codebase diff volume evaluation and fallback."""

    def __init__(self, config: LargeDiffFallbackConfig | None = None) -> None:
        self.config = config or LargeDiffFallbackConfig()
        self.pipeline = LargeDiffFallbackPipeline(self.config)

    def evaluate_tier(
        self,
        files: list[DiffFileEntry],
        declared_total_files: int | None = None,
        is_api_truncated: bool = False,
    ) -> tuple[DiffVolumeTier, bool, str | None]:
        """Evaluates volume tier and truncation status without full synthesis."""
        return self.pipeline.evaluate_tier(
            files,
            declared_total_files=declared_total_files,
            is_api_truncated=is_api_truncated,
        )

    def process_diff(
        self,
        files: list[DiffFileEntry],
        declared_total_files: int | None = None,
        is_api_truncated: bool = False,
        commit_message: str | None = None,
    ) -> DiffFallbackVerdict:
        """Processes diff entries and returns complete diagnostic verdict."""
        return self.pipeline.process(
            files,
            declared_total_files=declared_total_files,
            is_api_truncated=is_api_truncated,
            commit_message=commit_message,
        )

    @staticmethod
    def parse_numstat_line(line: str) -> DiffFileEntry | None:
        """Parses a standard `git diff --numstat` line into a DiffFileEntry.

        Example formats:
            10\t5\tsrc/main.py
            -\t-\tassets/logo.png (binary)
            12\t0\told_name.py => new_name.py
        """
        line = line.strip()
        if not line:
            return None
        parts = line.split("\t")
        if len(parts) < 3:
            return None

        add_str, del_str, path_part = parts[0], parts[1], parts[2]
        additions = int(add_str) if add_str.isdigit() else 0
        deletions = int(del_str) if del_str.isdigit() else 0

        is_renamed = False
        old_path: str | None = None
        target_path = path_part

        if " => " in path_part:
            is_renamed = True
            # Handle {old => new} or old => new
            if "{" in path_part and "}" in path_part:
                prefix = path_part.split("{")[0]
                inner = path_part.split("{")[1].split("}")[0]
                suffix = path_part.split("}")[1]
                old_sub, new_sub = inner.split(" => ")
                old_path = f"{prefix}{old_sub}{suffix}"
                target_path = f"{prefix}{new_sub}{suffix}"
            else:
                old_path, target_path = path_part.split(" => ")

        category = DiffPathClassifier.classify_path(target_path)
        is_generated = category in {DiffCategory.LOCKFILE, DiffCategory.GENERATED}

        return DiffFileEntry(
            path=target_path,
            additions=additions,
            deletions=deletions,
            category=category,
            is_generated=is_generated,
            is_renamed=is_renamed,
            old_path=old_path,
        )
