# [INPUT]: CanonicalFileKind, Path
# [OUTPUT]: BootstrapLifecycleRunner, BootstrapRitualState
# [POS]: agent/workspace_rules/canonical_protocol/bootstrap_lifecycle_runner.py

"""Bootstrap lifecycle runner managing birth rituals and auto-pruning upon initialization.

[INPUT]
- CanonicalFileKind: File kind enum for BOOTSTRAP.md.
- Path: Directory path for workspace.

[OUTPUT]
- BootstrapRitualState: Status of the onboarding birth sequence.
- BootstrapLifecycleRunner: Executes birth sequences and securely prunes BOOTSTRAP.md after completion.

[POS]
Lifecycle runner layer in canonical workspace protocol subsystem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .canonical_types import CanonicalFileKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootstrapRitualState:
    """State of workspace onboarding birth ritual."""

    has_pending_bootstrap: bool
    bootstrap_file_path: str
    ritual_instruction: str


class BootstrapLifecycleRunner:
    """Detects first-run birth sequence ritual and automatically prunes BOOTSTRAP.md upon completion."""

    def check_bootstrap_status(self, directory: Path) -> BootstrapRitualState:
        """Inspect workspace for active BOOTSTRAP.md file."""
        bootstrap_path = directory / CanonicalFileKind.BOOTSTRAP.value
        if not bootstrap_path.is_file():
            return BootstrapRitualState(
                has_pending_bootstrap=False,
                bootstrap_file_path="",
                ritual_instruction="",
            )

        try:
            content = bootstrap_path.read_text(encoding="utf-8").strip()
            if not content:
                return BootstrapRitualState(
                    has_pending_bootstrap=False,
                    bootstrap_file_path=str(bootstrap_path),
                    ritual_instruction="",
                )

            instruction = (
                "### 🐣 [First-Run Birth Sequence Ritual Active]\n"
                "This workspace contains a new BOOTSTRAP.md initialization sequence.\n"
                f"Please guide the user through the following setup steps:\n\n{content}"
            )
            return BootstrapRitualState(
                has_pending_bootstrap=True,
                bootstrap_file_path=str(bootstrap_path),
                ritual_instruction=instruction,
            )
        except OSError as exc:
            logger.warning("Failed reading bootstrap file %s: %s", bootstrap_path, exc)
            return BootstrapRitualState(
                has_pending_bootstrap=False,
                bootstrap_file_path=str(bootstrap_path),
                ritual_instruction="",
            )

    def complete_and_prune_bootstrap(self, directory: Path) -> bool:
        """Safely delete BOOTSTRAP.md once initialization ritual is successfully accomplished."""
        bootstrap_path = directory / CanonicalFileKind.BOOTSTRAP.value
        if not bootstrap_path.is_file():
            return False

        try:
            bootstrap_path.unlink(missing_ok=True)
            logger.info("Successfully pruned completed birth sequence: %s", bootstrap_path)
            return True
        except OSError as exc:
            logger.error("Failed to prune bootstrap file %s: %s", bootstrap_path, exc)
            return False
