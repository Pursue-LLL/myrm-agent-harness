"""Suite orchestrating single-tier rule override resolution, dynamic reloading, and audit explanations."""

from __future__ import annotations

from typing import Dict, List, Optional

from .single_tier_override_types import (
    OverrideResolutionKind,
    SingleTierRuleAssemblyReceipt,
)
from .single_tier_rule_resolver import SingleTierRuleResolver


class SingleTierWorkspaceRuleOverrideInterceptorSuite:
    """End-to-end suite providing single-tier override interception, reloading, and audit inspection."""

    def __init__(self, resolver: Optional[SingleTierRuleResolver] = None) -> None:
        self._resolver = resolver or SingleTierRuleResolver()
        self._cached_receipts: Dict[str, SingleTierRuleAssemblyReceipt] = {}

    @property
    def resolver(self) -> SingleTierRuleResolver:
        """Access underlying rule resolver."""
        return self._resolver

    def assemble_rules(
        self,
        target_dir: str,
        workspace_root: str,
        opt_out_context_files: bool = False,
        use_cache: bool = True,
    ) -> SingleTierRuleAssemblyReceipt:
        """Resolve and assemble effective rule chain for a directory with caching support."""
        cache_key = f"{target_dir}:{workspace_root}:{opt_out_context_files}"
        if use_cache and cache_key in self._cached_receipts:
            return self._cached_receipts[cache_key]

        receipt = self._resolver.resolve_hierarchy(
            target_dir=target_dir,
            workspace_root=workspace_root,
            opt_out_context_files=opt_out_context_files,
        )
        self._cached_receipts[cache_key] = receipt
        return receipt

    def reload_rules(
        self,
        target_dir: str,
        workspace_root: str,
    ) -> SingleTierRuleAssemblyReceipt:
        """Force cache invalidation and re-scan files corresponding to /reload command."""
        return self.assemble_rules(
            target_dir=target_dir,
            workspace_root=workspace_root,
            opt_out_context_files=False,
            use_cache=False,
        )

    def clear_cache(self) -> None:
        """Clear all cached rule assembly receipts."""
        self._cached_receipts.clear()

    def explain_override_effect(
        self,
        target_dir: str,
        workspace_root: str,
    ) -> Dict[str, object]:
        """Provide detailed human and machine readable diagnostics on override effects."""
        receipt = self.assemble_rules(target_dir, workspace_root, use_cache=False)

        inherited_parents: List[str] = []
        active_overrides: List[str] = []

        for entry in receipt.effective_rule_chain:
            if entry.is_override:
                active_overrides.append(entry.file_path)
            else:
                inherited_parents.append(entry.file_path)

        return {
            "target_dir": receipt.target_dir,
            "workspace_root": receipt.workspace_root,
            "resolution": receipt.resolution.value,
            "is_overridden": receipt.resolution == OverrideResolutionKind.SINGLE_TIER_OVERRIDDEN,
            "active_overrides": active_overrides,
            "inherited_rules": inherited_parents,
            "suppressed_default_files": receipt.suppressed_default_files,
            "total_effective_files": len(receipt.effective_rule_chain),
            "assembly_hash": receipt.assembly_hash,
        }
