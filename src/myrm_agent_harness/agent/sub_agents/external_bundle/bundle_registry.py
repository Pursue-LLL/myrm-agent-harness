"""Registry for External Agent Profile Bundles with Sandbox Security Gate.

[INPUT]
- __future__
- os
- shutil
- types

[OUTPUT]
- ExternalBundleSecurityViolationError
- ExternalBundleNotFoundError
- ExternalAgentBundleRegistry

[POS]
Registry for External Agent Profile Bundles with Sandbox Security Gate.

"""

from __future__ import annotations

import os
import shutil

from .types import (
    BundleExecutionModeEnum,
    ExternalAgentTypeEnum,
    ExternalBundleProfileSpec,
)


class ExternalBundleSecurityViolationError(Exception):
    """Raised when an external subagent attempts to breach directory or privilege boundaries."""


class ExternalBundleNotFoundError(Exception):
    """Raised when a requested external agent bundle is not registered."""


class ExternalAgentBundleRegistry:
    """Manages containerized and native CLI external agent profile bundles."""

    def __init__(self) -> None:
        self._bundles: dict[str, ExternalBundleProfileSpec] = {}
        self._initialize_builtins()

    def _initialize_builtins(self) -> None:
        """Register reference bundles for Claude Code, Codex, and Gemini CLI."""
        claude_bundle = ExternalBundleProfileSpec(
            bundle_id="subagent-claude-code",
            agent_type=ExternalAgentTypeEnum.CLAUDE_CODE,
            display_name="Claude Code Specialist",
            description="Deep reasoning coding agent specializing in architectural refactoring, AST linting, and PR review",
            binary_name="claude",
            command_template="claude --print -p '{prompt}'",
            capabilities=["code_generation", "code_review", "refactoring", "git_ops"],
            env_whitelist=["ANTHROPIC_API_KEY", "HOME", "PATH", "LANG"],
            allowed_roots=[],
            execution_mode=BundleExecutionModeEnum.SANDBOX_ISOLATED,
            max_concurrency=4,
            is_installed=bool(shutil.which("claude")),
            version="0.2.29",
        )

        codex_bundle = ExternalBundleProfileSpec(
            bundle_id="subagent-codex",
            agent_type=ExternalAgentTypeEnum.CODEX,
            display_name="OpenAI Codex Worker",
            description="High-velocity code completion and multi-instance implementation worker",
            binary_name="codex",
            command_template="codex exec --headless '{prompt}'",
            capabilities=["code_generation", "unit_testing", "debugging", "scaffolding"],
            env_whitelist=["OPENAI_API_KEY", "HOME", "PATH", "LANG"],
            allowed_roots=[],
            execution_mode=BundleExecutionModeEnum.SANDBOX_ISOLATED,
            max_concurrency=6,
            is_installed=bool(shutil.which("codex")),
            version="1.4.0",
        )

        gemini_bundle = ExternalBundleProfileSpec(
            bundle_id="subagent-gemini-cli",
            agent_type=ExternalAgentTypeEnum.GEMINI_CLI,
            display_name="Gemini CLI Agent",
            description="Multimodal CLI agent with ultra-long context for massive codebase documentation and exploration",
            binary_name="gemini",
            command_template="gemini run --quiet '{prompt}'",
            capabilities=["multimodal_analysis", "doc_writer", "codebase_index"],
            env_whitelist=["GEMINI_API_KEY", "HOME", "PATH"],
            allowed_roots=[],
            execution_mode=BundleExecutionModeEnum.SANDBOX_ISOLATED,
            max_concurrency=4,
            is_installed=bool(shutil.which("gemini")),
            version="2.0.0",
        )

        self.register_bundle(claude_bundle)
        self.register_bundle(codex_bundle)
        self.register_bundle(gemini_bundle)

    def register_bundle(self, spec: ExternalBundleProfileSpec) -> None:
        """Register or overwrite an external subagent bundle profile."""
        self._bundles[spec.bundle_id] = spec

    def get_bundle(self, bundle_id: str) -> ExternalBundleProfileSpec:
        """Retrieve registered bundle by ID or raise ExternalBundleNotFoundError."""
        if bundle_id not in self._bundles:
            raise ExternalBundleNotFoundError(
                f"External agent bundle '{bundle_id}' not found in registry. Registered bundles: {list(self._bundles.keys())}"
            )
        return self._bundles[bundle_id]

    def list_bundles(self) -> list[ExternalBundleProfileSpec]:
        """List all registered external agent bundles."""
        return list(self._bundles.values())

    def probe_host_environment(self, bundle_id: str) -> bool:
        """Probe host PATH to determine if bundle binary is executable."""
        bundle = self.get_bundle(bundle_id)
        path = shutil.which(bundle.binary_name)
        is_installed = bool(path)
        # Update cache
        bundle.is_installed = is_installed
        return is_installed

    def validate_directory_boundary(
        self,
        bundle_id: str,
        target_path: str,
        session_workspace_root: str,
    ) -> str:
        """Ensure the target workdir strictly resides within the session workspace root.

        Raises ExternalBundleSecurityViolationError on directory traversal or unpermitted access.
        """
        bundle = self.get_bundle(bundle_id)
        norm_target = os.path.realpath(os.path.abspath(target_path))
        norm_root = os.path.realpath(os.path.abspath(session_workspace_root))

        # Check if target is inside session workspace root
        if norm_target == norm_root or norm_target.startswith(norm_root + os.sep):
            return norm_target

        # Check explicit allowed roots
        for allowed in bundle.allowed_roots:
            norm_allowed = os.path.realpath(os.path.abspath(allowed))
            if norm_target == norm_allowed or norm_target.startswith(norm_allowed + os.sep):
                return norm_target

        raise ExternalBundleSecurityViolationError(
            f"Security Violation: External subagent '{bundle.bundle_id}' denied access to target '{target_path}'. "
            f"Must reside within workspace root '{session_workspace_root}'."
        )
