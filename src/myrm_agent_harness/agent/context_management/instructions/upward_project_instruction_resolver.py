"""Recursively resolves project instructions upward along directory tree and claims legacy skills.

[INPUT]
- agent.context_management.instructions.upward_instruction_types::EcosystemPriority, InstructionEcosystem,
  LegacySkillsDirectory, ScannedInstructionFile, UpwardResolutionResult (POS: Types and models for upward
  instruction.)

[OUTPUT]
- UpwardProjectInstructionResolver: Recursively resolves project instructions upward along directory tree and
  claims legacy skills.

[POS]
Recursively resolves project instructions upward along directory tree and claims legacy skills.
"""

# ============================================================================
# # UpwardProjectInstructionResolver - Recursive Discovery & Migration Gate (Item 148)
# # Discovers instructions upward from deep subdirectories to repo root boundary,
# # merges cross-tool hierarchy (MYRM > AGENTS > CLAUDE > CURSOR > CODEX),
# # and auto-mounts legacy skills from ~/.claude, ~/.codex, ~/.cursor without migration.
# ============================================================================

from __future__ import annotations

import re
from pathlib import Path

from .upward_instruction_types import (
    EcosystemPriority,
    InstructionEcosystem,
    LegacySkillsDirectory,
    ScannedInstructionFile,
    UpwardResolutionResult,
)

_PROJECT_ROOT_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
)

_ECOSYSTEM_FILE_CANDIDATES: tuple[tuple[str, InstructionEcosystem, int], ...] = (
    ("MYRM.md", InstructionEcosystem.MYRM, EcosystemPriority.MYRM),
    (".myrm/rules.md", InstructionEcosystem.MYRM, EcosystemPriority.MYRM),
    ("AGENTS.md", InstructionEcosystem.AGENTS_MD, EcosystemPriority.AGENTS_MD),
    ("CLAUDE.md", InstructionEcosystem.CLAUDE_MD, EcosystemPriority.CLAUDE_MD),
    (".cursorrules", InstructionEcosystem.CURSOR_RULES, EcosystemPriority.CURSOR_RULES),
    ("CODEX.md", InstructionEcosystem.CODEX_MD, EcosystemPriority.CODEX_MD),
)

_ZERO_WIDTH_CHARS = re.compile(r"[\u200b\u200c\u200d\ufeff\u200e\u200f]")


class UpwardProjectInstructionResolver:
    """Recursively resolves project instructions upward along directory tree and claims legacy skills."""

    def __init__(self, max_file_chars: int = 12000, total_budget_chars: int = 36000) -> None:
        self.max_file_chars = max_file_chars
        self.total_budget_chars = total_budget_chars

    def find_repo_root_boundary(self, start_dir: Path, custom_boundary: Path | None = None) -> Path:
        """Ascends directory hierarchy to identify the closest project root boundary."""
        if custom_boundary is not None and custom_boundary.exists():
            return custom_boundary.resolve()

        curr = start_dir.resolve()
        while True:
            for marker in _PROJECT_ROOT_MARKERS:
                if (curr / marker).exists():
                    return curr

            parent = curr.parent
            if parent == curr:  # Reached filesystem root
                return start_dir.resolve()
            curr = parent

    def resolve_upward(
        self,
        start_dir: str | Path,
        max_depth: int = 10,
        custom_boundary: str | Path | None = None,
        user_home: str | Path | None = None,
    ) -> UpwardResolutionResult:
        """Ascends directory path collecting instruction files from child up to boundary root."""
        start_path = Path(start_dir).resolve()
        if start_path.is_file():
            start_path = start_path.parent

        boundary_path = self.find_repo_root_boundary(
            start_path,
            Path(custom_boundary).resolve() if custom_boundary else None,
        )

        dirs_to_scan: list[tuple[Path, int]] = []
        curr = start_path
        depth = 0

        while depth <= max_depth:
            dirs_to_scan.append((curr, depth))
            if curr == boundary_path or curr.parent == curr:
                break
            curr = curr.parent
            depth += 1

        scanned_files: list[ScannedInstructionFile] = []
        for directory, cur_depth in dirs_to_scan:
            best_for_dir: ScannedInstructionFile | None = None

            for filename, eco, prio in _ECOSYSTEM_FILE_CANDIDATES:
                target_file = directory / filename
                if target_file.is_file():
                    try:
                        raw_content = target_file.read_text(encoding="utf-8", errors="ignore")
                        cleaned = _ZERO_WIDTH_CHARS.sub("", raw_content).strip()
                        if not cleaned:
                            continue

                        truncated = cleaned[: self.max_file_chars]
                        tokens_est = max(1, len(truncated) // 4)

                        scanned = ScannedInstructionFile(
                            file_path=str(target_file.resolve()),
                            directory_path=str(directory),
                            depth=cur_depth,
                            ecosystem=eco,
                            priority=prio,
                            content=truncated,
                            file_size_bytes=len(cleaned.encode("utf-8")),
                            tokens_estimate=tokens_est,
                        )

                        # In same directory, highest ecosystem priority wins
                        if best_for_dir is None or scanned.priority > best_for_dir.priority:
                            best_for_dir = scanned
                    except Exception:
                        continue

            if best_for_dir is not None:
                scanned_files.append(best_for_dir)

        # Sort so root (deepest depth) appears first, moving down to child directory (depth 0)
        scanned_files.sort(key=lambda f: f.depth, reverse=True)

        merged_blocks: list[str] = []
        current_used_chars = 0
        total_tokens = 0

        for sfile in scanned_files:
            if current_used_chars + len(sfile.content) > self.total_budget_chars:
                avail = max(0, self.total_budget_chars - current_used_chars)
                if avail > 100:
                    merged_blocks.append(
                        f"<!-- Origin: {sfile.file_path} (Depth: {sfile.depth}, Eco: {sfile.ecosystem}) -->\n"
                        f"{sfile.content[:avail]}\n[TRUNCATED_DUE_TO_BUDGET]"
                    )
                break

            merged_blocks.append(
                f"<!-- Origin: {sfile.file_path} (Depth: {sfile.depth}, Eco: {sfile.ecosystem}) -->\n"
                f"{sfile.content}"
            )
            current_used_chars += len(sfile.content)
            total_tokens += sfile.tokens_estimate

        final_markdown = ""
        if merged_blocks:
            final_markdown = (
                f'<project_instructions hierarchy="upward_resolved" '
                f'root="{boundary_path}" leaf="{start_path}">\n'
                f"{'\n\n---\n\n'.join(merged_blocks)}\n"
                f"</project_instructions>"
            )

        # Auto-mount foreign legacy skills
        legacy_dirs = self.scan_legacy_skills_directories(user_home=user_home, workspace_dir=boundary_path)

        return UpwardResolutionResult(
            start_dir=str(start_path),
            root_boundary_dir=str(boundary_path),
            scanned_files=scanned_files,
            merged_instructions_markdown=final_markdown,
            total_tokens_estimate=total_tokens,
            legacy_skills_dirs=legacy_dirs,
        )

    def scan_legacy_skills_directories(
        self,
        user_home: str | Path | None = None,
        workspace_dir: str | Path | None = None,
    ) -> list[LegacySkillsDirectory]:
        """Auto-detects foreign tool legacy skill directories for zero-migration reuse."""
        home_path = Path(user_home).resolve() if user_home else Path.home()
        ws_path = Path(workspace_dir).resolve() if workspace_dir else None

        candidates: list[tuple[InstructionEcosystem, Path]] = [
            (InstructionEcosystem.CLAUDE_MD, home_path / ".claude" / "skills"),
            (InstructionEcosystem.CODEX_MD, home_path / ".codex" / "skills"),
            (InstructionEcosystem.CURSOR_RULES, home_path / ".cursor" / "skills"),
        ]
        if ws_path:
            candidates.append((InstructionEcosystem.AGENTS_MD, ws_path / ".agents" / "skills"))

        legacy_dirs: list[LegacySkillsDirectory] = []
        for eco, dir_path in candidates:
            if dir_path.is_dir():
                try:
                    entries = [p.name for p in dir_path.iterdir() if p.is_dir() or p.name.endswith(".md")]
                    legacy_dirs.append(
                        LegacySkillsDirectory(
                            ecosystem=eco,
                            directory_path=str(dir_path),
                            skills_count=len(entries),
                            is_active=True,
                            manifest_names=entries[:15],
                        )
                    )
                except Exception:
                    continue

        return legacy_dirs
