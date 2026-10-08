"""Suite managing top-priority system prompt append injection and anti-drift verification.

[INPUT]
- agent.context_management.system_append_channel.system_append_loader::SystemPromptAppendLoader (POS: Loader
  discovering system append and replace directive files across workspace and user home.)
- agent.context_management.system_append_channel.system_append_types::AppendPromptSource, PromptChannelKind,
  SystemPromptAssemblyReceipt (POS: Types and models for system prompt strong append channel suite.)

[OUTPUT]
- SystemPromptStrongAppendChannelSuite: Orchestrates top-priority system prompt append channels and anti-drift
  validation.

[POS]
Suite managing top-priority system prompt append injection and anti-drift verification.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional

from .system_append_loader import SystemPromptAppendLoader
from .system_append_types import (
    AppendPromptSource,
    PromptChannelKind,
    SystemPromptAssemblyReceipt,
)


class SystemPromptStrongAppendChannelSuite:
    """Orchestrates top-priority system prompt append channels and anti-drift validation."""

    def __init__(self, loader: Optional[SystemPromptAppendLoader] = None) -> None:
        self._loader = loader or SystemPromptAppendLoader()

    @property
    def loader(self) -> SystemPromptAppendLoader:
        """Access underlying append loader."""
        return self._loader

    def assemble_system_prompt(
        self,
        base_system_prompt: str,
        workspace_root: str,
        allow_full_replace: bool = False,
        mandatory_anti_drift_keywords: Optional[List[str]] = None,
    ) -> SystemPromptAssemblyReceipt:
        """Assemble base system prompt with strong append channel directives."""
        append_sources, replace_source = self._loader.discover_sources(
            workspace_root=workspace_root,
            allow_full_replace=allow_full_replace,
        )

        base_clean = base_system_prompt.strip()
        base_digest = hashlib.sha256(base_clean.encode("utf-8")).hexdigest()[:12]

        injected_channels: List[PromptChannelKind] = [PromptChannelKind.BASE_CORE_SYSTEM]

        # Case 1: Full replace enabled and present
        if replace_source is not None and allow_full_replace:
            final_prompt = replace_source.content
            appended_digest = replace_source.digest
            injected_channels = [PromptChannelKind.FULL_REPLACE_SYSTEM]
            is_replaced = True
            active_sources = [replace_source]
        else:
            # Case 2: Standard Strong Append Channel
            is_replaced = False
            active_sources = append_sources

            if len(append_sources) > 0:
                # Sort by priority ascending (e.g. global=80, workspace=100)
                sorted_sources = sorted(append_sources, key=lambda s: s.priority)
                append_blocks: List[str] = []
                for src in sorted_sources:
                    append_blocks.append(
                        f"<!-- [SYSTEM_APPEND_DIRECTIVE] Source: {src.source_path} -->\n{src.content}"
                    )
                    if src.channel_kind not in injected_channels:
                        injected_channels.append(src.channel_kind)

                all_appended_text = "\n\n".join(append_blocks)
                appended_digest = hashlib.sha256(all_appended_text.encode("utf-8")).hexdigest()[:12]

                final_prompt = (
                    f"{base_clean}\n\n"
                    f"<<<SYSTEM_APPEND_STRONG_DIRECTIVES>>>\n"
                    f"{all_appended_text}\n"
                    f"<<<END_SYSTEM_APPEND_STRONG_DIRECTIVES>>>"
                )
            else:
                appended_digest = "none"
                final_prompt = base_clean

        # Anti-drift verification
        anti_drift_ok = True
        if mandatory_anti_drift_keywords:
            for kw in mandatory_anti_drift_keywords:
                if kw not in final_prompt:
                    anti_drift_ok = False
                    break

        assembly_hash = hashlib.sha256(final_prompt.encode("utf-8")).hexdigest()[:16]

        return SystemPromptAssemblyReceipt(
            base_prompt_digest=base_digest,
            appended_content_digest=appended_digest,
            final_system_prompt=final_prompt,
            is_replaced=is_replaced,
            injected_channels=injected_channels,
            anti_drift_verified=anti_drift_ok,
            active_sources=active_sources,
            assembly_hash=assembly_hash,
        )
