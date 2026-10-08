"""Workspace File Access Guard and Markdown link inspector.

[INPUT]
- Chat Markdown texts, file paths, and requested action types.

[OUTPUT]
- Policy enforcement verdicts, verified desktop launch paths, and extracted link collections.

[POS]
- Harness core security barrier protecting host filesystem boundaries from agent abuse.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.workspace_boundary.resolver import (
    ActualPathLinkResolver,
)
from myrm_agent_harness.core.security.workspace_boundary.types import (
    FileActionType,
    PathResolutionResult,
    SymlinkEscapeError,
    WorkspaceBoundaryError,
    WorkspaceBoundaryPolicy,
)

_MARKDOWN_LINK_REGEX = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_DANGEROUS_CLI_PREFIX = re.compile(r"^-+")


class WorkspaceFileAccessGuard:
    """Security guard enforcing workspace isolation and link action permissions."""

    def __init__(self, policy: WorkspaceBoundaryPolicy) -> None:
        self._policy = policy
        self._resolver = ActualPathLinkResolver(policy=policy)

    @property
    def policy(self) -> WorkspaceBoundaryPolicy:
        """Current boundary policy."""
        return self._policy

    @property
    def resolver(self) -> ActualPathLinkResolver:
        """Underlying path resolver."""
        return self._resolver

    def evaluate_access(
        self,
        raw_target: str,
        action: FileActionType = FileActionType.LAUNCH_DEFAULT_APP,
    ) -> PathResolutionResult:
        """Evaluate whether a specific file action is permitted for the given target."""
        res = self._resolver.resolve(raw_target)

        # Action-specific permission overrides or refinement
        if action == FileActionType.LAUNCH_DEFAULT_APP and not res.can_launch:
            return res
        if action == FileActionType.READ_CONTENT and not res.can_read:
            return res
        if action == FileActionType.REVEAL_IN_FOLDER and not res.can_reveal:
            return res

        return res

    def assert_action_permitted(
        self,
        raw_target: str,
        action: FileActionType = FileActionType.LAUNCH_DEFAULT_APP,
    ) -> PathResolutionResult:
        """Assert that an action is strictly authorized, raising domain exceptions on refusal."""
        res = self.evaluate_access(raw_target=raw_target, action=action)

        if res.verdict.name == "REFUSED_SYMLINK_ESCAPE":
            raise SymlinkEscapeError(f"Symlink escape blocked: {res.error_message}")
        if action in {FileActionType.LAUNCH_DEFAULT_APP, FileActionType.READ_CONTENT, FileActionType.EDIT_CONTENT}:
            if not res.is_inside_workspace:
                raise WorkspaceBoundaryError(
                    f"Action '{action.value}' refused: target is outside workspace boundaries. {res.error_message}"
                )
            if not res.is_regular_file:
                raise WorkspaceBoundaryError(
                    f"Action '{action.value}' refused: target is not a regular file. {res.error_message}"
                )
        elif action == FileActionType.REVEAL_IN_FOLDER:
            if not res.can_reveal:
                raise WorkspaceBoundaryError(
                    f"Reveal refused: target does not exist on disk. {res.error_message}"
                )

        return res

    def parse_and_resolve_markdown_links(self, markdown_text: str) -> list[PathResolutionResult]:
        """Extract all file links from Markdown text and resolve each against workspace boundaries."""
        results: list[PathResolutionResult] = []
        for match in _MARKDOWN_LINK_REGEX.finditer(markdown_text):
            url_part = match.group(2).strip()
            # Ignore purely web/http schemes
            if url_part.startswith(("http://", "https://", "mailto:")):
                continue
            res = self._resolver.resolve(url_part)
            results.append(res)
        return results

    def sanitize_for_desktop_reveal(self, raw_target: str) -> str:
        """Verify and sanitize physical file path for safe operating system reveal or launch."""
        res = self._resolver.resolve(raw_target)
        if not res.can_reveal or not res.resolved_physical_path:
            raise WorkspaceBoundaryError(
                f"Cannot reveal path '{raw_target}': target does not exist or is invalid."
            )

        resolved_str = res.resolved_physical_path

        # Guard against argument injection (e.g. paths starting with '-' flag syntax)
        if _DANGEROUS_CLI_PREFIX.match(resolved_str):
            raise WorkspaceBoundaryError(
                f"Path '{resolved_str}' contains dangerous leading flag characters."
            )

        # Guard against control characters and null bytes
        if any(ord(c) < 32 for c in resolved_str):
            raise WorkspaceBoundaryError("Path contains illegal control characters.")

        return resolved_str
