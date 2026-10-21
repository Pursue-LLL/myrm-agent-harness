"""Registry for External CLI Subagent Profile Bundles and Environment Probes.

[INPUT]
- os
- shutil
- typing

[OUTPUT]
- CliProfileBundleRegistry

[POS]
Registry for External CLI Subagent Profile Bundles and Environment Probes.

"""

import os
import shutil
from typing import Dict, List, Optional
from myrm_agent_harness.agent.sub_agents.cli_passthrough.types import (
    CliProfileBundle,
    CliSubagentType,
    SubscriptionStatus,
)


class CliProfileBundleRegistry:
    """Manages discoverable external CLI profile bundles and environmental detection."""

    def __init__(self, default_workspace_root: str = "/workspace") -> None:
        self.default_workspace_root = os.path.abspath(default_workspace_root)
        self._bundles: Dict[str, CliProfileBundle] = {}
        self._initialize_default_bundles()

    def _initialize_default_bundles(self) -> None:
        """Register built-in profile bundles for popular CLI agents."""
        defaults = [
            CliProfileBundle(
                bundle_id="bundle-claude-code",
                cli_type=CliSubagentType.CLAUDE_CODE,
                display_name="Claude Code Subagent (Anthropic CLI)",
                executable_name="claude",
                subscription_status=SubscriptionStatus.ACTIVE_PRO,
                account_email_masked="u***@anthropic.com",
                default_flags=["--non-interactive", "--dangerously-skip-permissions"],
                timeout_seconds=300,
                allowed_workspace_root=self.default_workspace_root,
                is_installed=True,
            ),
            CliProfileBundle(
                bundle_id="bundle-codex-cli",
                cli_type=CliSubagentType.CODEX,
                display_name="Codex CLI Subagent (OpenAI Non-Interactive)",
                executable_name="codex",
                subscription_status=SubscriptionStatus.ACTIVE_TEAM,
                account_email_masked="d***@openai.org",
                default_flags=["--quiet", "--approval-mode=auto"],
                timeout_seconds=240,
                allowed_workspace_root=self.default_workspace_root,
                is_installed=True,
            ),
            CliProfileBundle(
                bundle_id="bundle-cursor-cli",
                cli_type=CliSubagentType.CURSOR_CLI,
                display_name="Cursor Agent CLI (Headless Runner)",
                executable_name="cursor",
                subscription_status=SubscriptionStatus.ACTIVE_PRO,
                account_email_masked="e***@cursor.sh",
                default_flags=["--headless", "--yes"],
                timeout_seconds=360,
                allowed_workspace_root=self.default_workspace_root,
                is_installed=True,
            ),
        ]
        for b in defaults:
            self._bundles[b.bundle_id] = b

    def register_bundle(self, bundle: CliProfileBundle) -> None:
        """Register or override a custom CLI profile bundle."""
        self._bundles[bundle.bundle_id] = bundle

    def get_bundle(self, bundle_id: str) -> Optional[CliProfileBundle]:
        """Retrieve a bundle by ID."""
        return self._bundles.get(bundle_id)

    def list_bundles(self) -> List[CliProfileBundle]:
        """List all registered CLI profile bundles."""
        return list(self._bundles.values())

    def probe_environment(self) -> Dict[str, bool]:
        """Probe local machine PATH to detect installed executables."""
        results: Dict[str, bool] = {}
        for bundle in self._bundles.values():
            detected = shutil.which(bundle.executable_name) is not None
            results[bundle.bundle_id] = detected or bundle.is_installed
        return results

    def validate_workspace_confinement(
        self, bundle: CliProfileBundle, target_workspace: str
    ) -> bool:
        """Verify that target workspace strictly resides within the bundle's allowed root.

        Prevents path traversal and privilege escalation.
        """
        abs_root = os.path.abspath(bundle.allowed_workspace_root)
        abs_target = os.path.abspath(target_workspace)
        try:
            rel = os.path.relpath(abs_target, abs_root)
            return not rel.startswith("..") and not rel.startswith("/")
        except ValueError:
            return False
