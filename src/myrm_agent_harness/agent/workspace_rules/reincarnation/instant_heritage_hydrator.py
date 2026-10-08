# [INPUT]: HeritageHydrationResult, Path
# [OUTPUT]: InstantHeritageHydrator
# [POS]: agent/workspace_rules/reincarnation/instant_heritage_hydrator.py

"""Instant heritage hydrator injecting prior generational wisdom and archiving REINCARNATION.md.

[INPUT]
- HeritageHydrationResult: Hydration contract result.
- Path: Filesystem paths.

[OUTPUT]
- InstantHeritageHydrator: Detects, injects, and auto-archives REINCARNATION.md.

[POS]
Lifecycle hydration layer in reincarnation subsystem eliminating permanent token tax.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
import shutil

from .reincarnation_types import HeritageHydrationResult

logger = logging.getLogger(__name__)


class InstantHeritageHydrator:
    """Detects REINCARNATION.md on first boot, injects generational wisdom, and immediately archives it."""

    REINCARNATION_FILENAME: str = "REINCARNATION.md"
    ARCHIVE_DIRNAME: str = ".reincarnation_archive"

    GEN_REGEX: re.Pattern[str] = re.compile(r"Generation\s*#?([0-9]+)", re.IGNORECASE)

    def detect_reincarnation_file(self, workspace_dir: Path) -> Path | None:
        """Check if REINCARNATION.md exists in the workspace root."""
        p = workspace_dir / self.REINCARNATION_FILENAME
        if p.is_file():
            return p
        return None

    def hydrate_heritage(
        self,
        workspace_dir: Path,
        auto_archive: bool = True,
    ) -> HeritageHydrationResult:
        """Read REINCARNATION.md, format System Prompt injection, and optionally archive file."""
        file_path = self.detect_reincarnation_file(workspace_dir)
        if not file_path:
            return HeritageHydrationResult(
                has_heritage=False,
                generation=0,
                injected_prompt_block="",
                archived_file_path="",
                is_archived=False,
            )

        try:
            content = file_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.error("Failed reading %s: %s", file_path, exc)
            return HeritageHydrationResult(
                has_heritage=False,
                generation=0,
                injected_prompt_block="",
                archived_file_path="",
                is_archived=False,
            )

        if not content:
            return HeritageHydrationResult(
                has_heritage=False,
                generation=0,
                injected_prompt_block="",
                archived_file_path="",
                is_archived=False,
            )

        # Extract generation number
        match = self.GEN_REGEX.search(content)
        generation = int(match.group(1)) if match else 1

        prompt_block = (
            "### 🧬 [Inter-Generational Heritage: Reincarnation Wisdom Injected]\n"
            "You have inherited hardened lessons, user taboos, and lineage pedigree from prior generations.\n"
            f"{content}\n"
            "--- [End of Heritage Context: Embody these hard lessons without repeating prior mistakes]"
        )

        archived_path_str = ""
        is_archived = False

        if auto_archive:
            archive_dir = workspace_dir / self.ARCHIVE_DIRNAME
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_dest = archive_dir / f"reincarnation_gen_{generation}.md"

            try:
                shutil.move(str(file_path), str(archive_dest))
                archived_path_str = str(archive_dest)
                is_archived = True
                logger.info("Successfully moved %s to archive: %s", file_path, archive_dest)
            except OSError as exc:
                logger.warning("Failed archiving %s: %s", file_path, exc)

        return HeritageHydrationResult(
            has_heritage=True,
            generation=generation,
            injected_prompt_block=prompt_block,
            archived_file_path=archived_path_str,
            is_archived=is_archived,
        )
