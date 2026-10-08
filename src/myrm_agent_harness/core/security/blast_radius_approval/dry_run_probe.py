"""
[POS] src/myrm_agent_harness/core/security/blast_radius_approval/dry_run_probe.py
[INPUT] time, glob, re, typing, types
[OUTPUT] DryRunProbeEngine
Pre-execution dry-run impact enumeration engine for destructive commands.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import glob
import logging
import re
import time

from .types import (
    DryRunImpactPreview,
    ImpactPreviewTarget,
    ImpactTargetType,
)

logger = logging.getLogger(__name__)

_MAX_PREVIEW_TARGETS: int = 15

# Regex identifying destructive rm commands with paths/globs
_RM_COMMAND_RE: re.Pattern[str] = re.compile(
    r"\brm\s+(?:-[a-zA-Z0-9_-]+\s+)*([^\s;|&]+)", re.IGNORECASE
)

# Regex identifying git clean/reset/force push commands
_GIT_DESTRUCTIVE_RE: re.Pattern[str] = re.compile(
    r"\bgit\s+(clean|reset|push\s+--force|branch\s+-D)\b", re.IGNORECASE
)

# Regex identifying drop/truncate database queries
_SQL_DESTRUCTIVE_RE: re.Pattern[str] = re.compile(
    r"\b(DROP\s+TABLE|TRUNCATE\s+TABLE|DELETE\s+FROM)\s+([a-zA-Z0-9_]+)",
    re.IGNORECASE,
)


class DryRunProbeEngine:
    """Evaluates blast radius and enumerates affected targets before command execution."""

    def is_destructive_command(self, command: str) -> bool:
        """Determine whether the command possesses destructive irreversible impact."""
        cmd = command.strip()
        if _RM_COMMAND_RE.search(cmd):
            return True
        if _GIT_DESTRUCTIVE_RE.search(cmd):
            return True
        if _SQL_DESTRUCTIVE_RE.search(cmd):
            return True
        return "vercel --prod" in cmd.lower()

    def probe_blast_radius(
        self,
        command: str,
        workspace_dir: str | None = None,
        timeout_seconds: float = 2.0,
    ) -> DryRunImpactPreview:
        """Run safe dry-run impact enumeration with timeout fallback."""
        start_time = time.perf_counter()
        cmd = command.strip()

        # Case 1: SQL destructive query
        sql_match = _SQL_DESTRUCTIVE_RE.search(cmd)
        if sql_match:
            op = sql_match.group(1).upper()
            table_name = sql_match.group(2)
            target = ImpactPreviewTarget(
                path_or_identifier=table_name,
                target_type=ImpactTargetType.DATABASE_TABLE,
                action=op.lower(),
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return DryRunImpactPreview(
                command=cmd,
                estimated_files_count=0,
                estimated_dirs_count=0,
                targets=(target,),
                is_truncated=False,
                probe_duration_ms=round(elapsed_ms, 2),
                is_fallback_static=False,
                summary=f"Database destruction: {op} on table '{table_name}'",
            )

        # Case 2: Git destructive action
        git_match = _GIT_DESTRUCTIVE_RE.search(cmd)
        if git_match:
            git_op = git_match.group(1).lower()
            target = ImpactPreviewTarget(
                path_or_identifier=git_op,
                target_type=ImpactTargetType.GIT_REF,
                action=f"git_{git_op.split()[0]}",
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return DryRunImpactPreview(
                command=cmd,
                estimated_files_count=1,
                estimated_dirs_count=0,
                targets=(target,),
                is_truncated=False,
                probe_duration_ms=round(elapsed_ms, 2),
                is_fallback_static=False,
                summary=f"Git revision impact: '{git_op}' may rewrite or discard worktree state",
            )

        # Case 3: Filesystem rm command
        rm_match = _RM_COMMAND_RE.search(cmd)
        if rm_match:
            raw_path = rm_match.group(1)
            return self._probe_filesystem_rm(
                command=cmd,
                raw_path=raw_path,
                workspace_dir=workspace_dir,
                start_time=start_time,
                timeout_seconds=timeout_seconds,
            )

        # Fallback for generic command
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return DryRunImpactPreview(
            command=cmd,
            estimated_files_count=0,
            estimated_dirs_count=0,
            targets=(),
            is_truncated=False,
            probe_duration_ms=round(elapsed_ms, 2),
            is_fallback_static=True,
            summary="Standard command without detected destructive targets",
        )

    def _probe_filesystem_rm(
        self,
        command: str,
        raw_path: str,
        workspace_dir: str | None,
        start_time: float,
        timeout_seconds: float,
    ) -> DryRunImpactPreview:
        """Enumerate filesystem targets for rm commands."""
        # Simulated/safe glob expansion
        search_pattern = raw_path
        if workspace_dir and not raw_path.startswith("/"):
            search_pattern = f"{workspace_dir}/{raw_path}"

        matched_items: list[str] = []
        is_fallback_static = False

        try:
            # Check if glob might match
            if "*" in search_pattern or "?" in search_pattern:
                matched_items = glob.glob(search_pattern, recursive=True)
                if not matched_items:
                    matched_items = [raw_path]
                    is_fallback_static = True
            else:
                matched_items = [raw_path]
        except Exception as e:
            logger.warning("Glob error during dry-run probe: %s", e)
            is_fallback_static = True
            matched_items = [raw_path]

        # Enforce target capping
        is_truncated = len(matched_items) > _MAX_PREVIEW_TARGETS
        selected_paths = matched_items[:_MAX_PREVIEW_TARGETS]

        targets_list: list[ImpactPreviewTarget] = []
        files_count = 0
        dirs_count = 0

        for p in selected_paths:
            # Heuristic: ends with slash or no extension with -r/-rf
            has_extension = bool(re.search(r"\.[a-zA-Z0-9_-]+$", p))
            is_dir = p.endswith("/") or (not has_extension and ("-r" in command or "-rf" in command))
            ttype = ImpactTargetType.DIRECTORY if is_dir else ImpactTargetType.FILE
            if is_dir:
                dirs_count += 1
            else:
                files_count += 1
            targets_list.append(
                ImpactPreviewTarget(
                    path_or_identifier=p,
                    target_type=ttype,
                    action="delete",
                )
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        if (time.perf_counter() - start_time) > timeout_seconds:
            is_fallback_static = True

        total_count = len(matched_items)
        summary = f"Will delete {total_count} target(s) matching '{raw_path}'"

        return DryRunImpactPreview(
            command=command,
            estimated_files_count=max(files_count, total_count if dirs_count == 0 else 0),
            estimated_dirs_count=dirs_count,
            targets=tuple(targets_list),
            is_truncated=is_truncated,
            probe_duration_ms=round(elapsed_ms, 2),
            is_fallback_static=is_fallback_static,
            summary=summary,
        )
