"""Physical path link resolver and canonical boundary analyzer.

[INPUT]
- Raw link targets (Markdown URLs, file:// URIs, relative/absolute paths), workspace roots.

[OUTPUT]
- Canonical PathResolutionResult determining realpath, containment, and file capabilities.

[POS]
- Harness core security resolver preventing path traversal and symlink escapes.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from myrm_agent_harness.core.security.workspace_boundary.types import (
    FileAccessVerdict,
    PathResolutionResult,
    WorkspaceBoundaryPolicy,
)


def _normalize_raw_link(raw_link: str) -> str:
    """Strip URI scheme, query/hash fragments, and URL percent-encoding."""
    cleaned = raw_link.strip()
    # Strip markdown trailing line anchors (e.g. #L10-L20)
    if "#" in cleaned:
        cleaned = cleaned.split("#", 1)[0]
    if "?" in cleaned:
        cleaned = cleaned.split("?", 1)[0]

    # Handle file:// URI scheme
    if cleaned.startswith("file://"):
        parsed = urllib.parse.urlparse(cleaned)
        # On Windows file:///C:/path -> parsed.path starts with /C:
        path_part = urllib.parse.unquote(parsed.path)
        if os.name == "nt" and len(path_part) > 2 and path_part[0] == "/" and path_part[2] == ":":
            return path_part[1:]
        return path_part

    return urllib.parse.unquote(cleaned)


def _is_path_inside_root(candidate: Path, root: Path) -> bool:
    """Determine whether candidate path is strictly within or equal to root."""
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


class ActualPathLinkResolver:
    """Resolves chat links and path references to verified on-disk locations."""

    def __init__(self, policy: WorkspaceBoundaryPolicy) -> None:
        self._policy = policy
        self._canonical_roots = [
            Path(os.path.realpath(r)).resolve() for r in policy.workspace_roots if r.strip()
        ]

    @property
    def canonical_roots(self) -> tuple[Path, ...]:
        """Immutable list of canonical workspace root paths."""
        return tuple(self._canonical_roots)

    def resolve(
        self,
        raw_target: str,
        custom_root: str | None = None,
    ) -> PathResolutionResult:
        """Resolve a raw link target to its canonical physical location and check boundary safety."""
        normalized = _normalize_raw_link(raw_target)
        if not normalized:
            primary_root = str(self._canonical_roots[0]) if self._canonical_roots else ""
            return PathResolutionResult(
                raw_input=raw_target,
                resolved_physical_path=None,
                workspace_root=primary_root,
                verdict=FileAccessVerdict.REFUSED_INVALID_PATH,
                is_inside_workspace=False,
                is_regular_file=False,
                can_launch=False,
                can_reveal=False,
                can_read=False,
                error_message="Target path cannot be empty.",
            )

        # Select primary root to evaluate against
        root_path = (
            Path(os.path.realpath(custom_root)).resolve()
            if custom_root
            else (self._canonical_roots[0] if self._canonical_roots else Path(os.getcwd()).resolve())
        )
        primary_root_str = str(root_path)

        # Construct candidate path
        candidate = Path(normalized)
        if not candidate.is_absolute():
            candidate = root_path / candidate

        # Lexical normalization without dereferencing symlinks
        lexical_candidate = Path(os.path.normpath(str(candidate)))
        lexical_inside = any(
            _is_path_inside_root(lexical_candidate, Path(os.path.normpath(str(r))))
            for r in [root_path, *self._canonical_roots]
        )
        is_symlink = candidate.is_symlink()

        # Verify existence
        if not candidate.exists() and not is_symlink:
            return PathResolutionResult(
                raw_input=raw_target,
                resolved_physical_path=None,
                workspace_root=primary_root_str,
                verdict=FileAccessVerdict.REFUSED_MISSING,
                is_inside_workspace=lexical_inside,
                is_regular_file=False,
                can_launch=False,
                can_reveal=False,
                can_read=False,
                error_message=f"Path '{normalized}' does not exist on disk.",
            )

        # Canonical realpath resolution (dereferences symlinks)
        real_target_str = os.path.realpath(str(candidate))
        resolved_path = Path(real_target_str).resolve()

        # Check physical containment
        is_physically_inside = any(
            _is_path_inside_root(resolved_path, r) for r in [root_path, *self._canonical_roots]
        )

        # Detect symlink escape
        if (lexical_inside and not is_physically_inside) or (is_symlink and not is_physically_inside):
            return PathResolutionResult(
                raw_input=raw_target,
                resolved_physical_path=str(resolved_path),
                workspace_root=primary_root_str,
                verdict=FileAccessVerdict.REFUSED_SYMLINK_ESCAPE,
                is_inside_workspace=False,
                is_regular_file=resolved_path.is_file(),
                can_launch=False,
                can_reveal=False,
                can_read=False,
                error_message=f"Symlink targets location '{resolved_path}' outside workspace boundary.",
            )

        if not is_physically_inside:
            return PathResolutionResult(
                raw_input=raw_target,
                resolved_physical_path=str(resolved_path),
                workspace_root=primary_root_str,
                verdict=FileAccessVerdict.REFUSED_OUTSIDE_WORKSPACE,
                is_inside_workspace=False,
                is_regular_file=resolved_path.is_file(),
                can_launch=False,
                can_reveal=True,  # Outside files may be revealed with warning if desired
                can_read=False,
                error_message="Target is located outside the authorized workspace root.",
            )

        if not resolved_path.is_file():
            return PathResolutionResult(
                raw_input=raw_target,
                resolved_physical_path=str(resolved_path),
                workspace_root=primary_root_str,
                verdict=FileAccessVerdict.REFUSED_NOT_FILE,
                is_inside_workspace=True,
                is_regular_file=False,
                can_launch=False,
                can_reveal=True,
                can_read=False,
                error_message="Target is a directory or special file, not a launchable regular file.",
            )

        return PathResolutionResult(
            raw_input=raw_target,
            resolved_physical_path=str(resolved_path),
            workspace_root=primary_root_str,
            verdict=FileAccessVerdict.ALLOWED,
            is_inside_workspace=True,
            is_regular_file=True,
            can_launch=True,
            can_reveal=True,
            can_read=True,
            error_message="",
        )
