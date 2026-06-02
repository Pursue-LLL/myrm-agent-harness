"""Workspace path resolver with intelligent auto-detection.

Provides bidirectional conversion between container abstract paths (/workspace/...)
and local filesystem paths. Container environments use paths directly; local
development environments need translation.

Design Philosophy:
- Zero configuration required (framework principle: out-of-the-box)
- Auto-detect workspace root from environment/markers/context
- Detailed diagnostics when resolution fails
- Aligns with langchain/anthropic SDK best practices

[INPUT]
- (none)

[OUTPUT]
- WorkspaceResolutionError: Raised when workspace root cannot be resolved.
- WorkspacePathResolver: Bidirectional path resolver with intelligent workspace au...

[POS]
Workspace path resolver with intelligent auto-detection.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class WorkspaceResolutionError(Exception):
    """Raised when workspace root cannot be resolved."""

    def __init__(self, message: str, details: dict, suggestions: list[str]):
        super().__init__(message)
        self.details = details
        self.suggestions = suggestions


class WorkspacePathResolver:
    """Bidirectional path resolver with intelligent workspace auto-detection.

    Used by:
    1. bash_executor: local skill paths -> container paths (PYTHONPATH)
    2. LocalExecutor: container paths -> local paths (working directory)

    Design:
    - Zero config required: auto-detects workspace root from env/markers/context
    - Detailed diagnostics: provides actionable error messages
    - Container-aware: detects /workspace, /.dockerenv, etc.
    """

    # Cached resolved workspace root (avoid repeated detection)
    _cached_workspace_root: Path | None = None

    @staticmethod
    def resolve_workspace_root() -> Path:
        """Intelligently resolve workspace root directory.

        Resolution order:
        1. WORKSPACE_ROOT env var (user explicit config)
        2. Container /workspace path (if exists)
        3. Project root markers (.git, pyproject.toml, etc.)
        4. Current working directory (fallback)

        Returns:
            Resolved workspace root Path.

        Raises:
            WorkspaceResolutionError: If resolution fails with diagnostic info.
        """
        # Return cached result if available
        if WorkspacePathResolver._cached_workspace_root:
            return WorkspacePathResolver._cached_workspace_root

        try:
            # 1. Check environment variable (highest priority)
            if workspace_env := os.getenv("WORKSPACE_ROOT"):
                workspace_path = Path(workspace_env).resolve()
                if workspace_path.exists():
                    logger.info(f" Workspace root from WORKSPACE_ROOT: {workspace_path}")
                    WorkspacePathResolver._cached_workspace_root = workspace_path
                    return workspace_path
                else:
                    logger.warning(f" WORKSPACE_ROOT={workspace_env} does not exist, continuing resolution")

            # 2. Container environment: check /workspace
            if WorkspacePathResolver._is_in_container():
                container_workspace = Path("/workspace")
                if container_workspace.exists():
                    logger.info(f" Container workspace detected: {container_workspace}")
                    WorkspacePathResolver._cached_workspace_root = container_workspace
                    return container_workspace

            # 3. Detect project root from markers
            if project_root := WorkspacePathResolver._detect_project_root():
                logger.info(f" Project root detected: {project_root}")
                WorkspacePathResolver._cached_workspace_root = project_root
                return project_root

            # 4. Fallback to current working directory
            cwd = Path.cwd()
            logger.info(f" Using current directory as workspace: {cwd}")
            WorkspacePathResolver._cached_workspace_root = cwd
            return cwd

        except Exception as e:
            # Enhanced error diagnostics
            diagnosis = WorkspacePathResolver._generate_diagnostics()
            raise WorkspaceResolutionError(
                "Failed to resolve workspace root directory",
                details=diagnosis,
                suggestions=[
                    "Set environment variable: export WORKSPACE_ROOT=/path/to/workspace",
                    "Run from project root directory (containing .git or pyproject.toml)",
                    "Ensure container mounts /workspace directory",
                    f"Check directory permissions: {Path.cwd()}",
                ],
            ) from e

    @staticmethod
    def _is_in_container() -> bool:
        """Detect if running in container environment."""
        return (
            Path("/.dockerenv").exists()
            or Path("/run/.containerenv").exists()
            or os.getenv("KUBERNETES_SERVICE_HOST") is not None
            or os.getenv("CONTAINER") == "podman"
        )

    @staticmethod
    def _detect_project_root() -> Path | None:
        """Detect project root directory from marker files."""
        markers = [".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", ".myrm"]
        current = Path.cwd()

        # Search upward from cwd
        for parent in [current, *current.parents]:
            for marker in markers:
                if (parent / marker).exists():
                    return parent

        return None

    @staticmethod
    def _generate_diagnostics() -> dict:
        """Generate detailed diagnostic information for troubleshooting."""
        cwd = Path.cwd()
        markers = [".git", "pyproject.toml", "package.json", ".myrm"]

        return {
            "cwd": str(cwd),
            "cwd_exists": cwd.exists(),
            "env_workspace_root": os.getenv("WORKSPACE_ROOT"),
            "is_container": WorkspacePathResolver._is_in_container(),
            "detected_markers": [marker for marker in markers if (cwd / marker).exists()],
            "parent_markers": [
                str(parent / marker) for parent in cwd.parents for marker in markers if (parent / marker).exists()
            ],
            "container_indicators": {
                "dockerenv": Path("/.dockerenv").exists(),
                "containerenv": Path("/run/.containerenv").exists(),
                "k8s": os.getenv("KUBERNETES_SERVICE_HOST") is not None,
            },
        }

    @staticmethod
    def to_container_path(local_path: Path | str, workspace_root: Path | str) -> str:
        """Convert a local absolute path to a container path.

        Example:
            local_path: /Users/xxx/workspace_123/.claude/skills/xxx
            workspace_root: /Users/xxx/workspace_123/
            returns: /workspace/.claude/skills/xxx

        Args:
            local_path: Local absolute path.
            workspace_root: Workspace root directory.

        Returns:
            Container path (prefixed with /workspace/).

        Raises:
            ValueError: If local_path is not under workspace_root.
        """
        local_path = Path(local_path).resolve()
        workspace_root = Path(workspace_root).resolve()

        try:
            relative_path = local_path.relative_to(workspace_root)

            if str(relative_path) == ".":
                return "/workspace"

            return f"/workspace/{relative_path.as_posix()}"
        except ValueError as e:
            raise ValueError(f"Path '{local_path}' is not under workspace_root '{workspace_root}'") from e

    @staticmethod
    def to_container_paths(local_paths: list[str], workspace_root: Path | str) -> list[str]:
        """Batch convert local paths to container paths.

        Args:
            local_paths: List of local absolute paths.
            workspace_root: Workspace root directory.

        Returns:
            List of container paths (failed conversions are skipped).
        """
        workspace_root = Path(workspace_root)
        container_paths = []

        for local_path in local_paths:
            try:
                container_path = WorkspacePathResolver.to_container_path(local_path, workspace_root)
                container_paths.append(container_path)
                logger.info(f" Path converted: {local_path} -> {container_path}")
            except ValueError as e:
                logger.warning(f" Path conversion failed: {e}")
                continue

        return container_paths

    @staticmethod
    def to_local_path(container_path: str, workspace_root: Path | str | None) -> Path | None:
        """Convert a container path to a local path with auto-resolution.

        Rules:
        - /workspace -> workspace_root
        - /workspace/xxx -> workspace_root/xxx
        - Other paths -> used directly (assumed absolute)

        Design:
        - Auto-resolves workspace_root if None (zero config required)
        - Falls back to intelligent detection (env/markers/container)

        Args:
            container_path: Container path.
            workspace_root: Workspace root directory (optional, auto-resolved if None).

        Returns:
            Local path, or None if conversion is not possible.
        """
        # Auto-resolve workspace_root if not provided (zero config)
        if not workspace_root:
            try:
                workspace_root = WorkspacePathResolver.resolve_workspace_root()
                logger.info(f" Auto-resolved workspace_root: {workspace_root}")
            except WorkspaceResolutionError as e:
                logger.error(
                    f" Failed to auto-resolve workspace_root for {container_path}\n"
                    f"Details: {e.details}\n"
                    f"Suggestions:\n" + "\n".join(f" - {s}" for s in e.suggestions)
                )
                return None

        workspace_root = Path(workspace_root)

        if container_path == "/workspace":
            return workspace_root

        if container_path.startswith("/workspace/"):
            relative_path = container_path[len("/workspace/") :]
            resolved_path = workspace_root / relative_path
            logger.info(f" Work dir resolved: {container_path} -> {resolved_path}")
            return resolved_path

        return Path(container_path)

    @staticmethod
    def is_container_path(path: str) -> bool:
        """Check if a path is a container abstract path (/workspace prefix).

        Args:
            path: Path string.

        Returns:
            True if the path starts with /workspace.
        """
        return path == "/workspace" or path.startswith("/workspace/")
