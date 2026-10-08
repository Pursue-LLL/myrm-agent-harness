"""System prompt strong append channel package.

[INPUT]
- agent.context_management.system_append_channel.system_append_loader::SystemPromptAppendLoader (POS: Loader
  discovering system append and replace directive files across workspace and user home.)
- agent.context_management.system_append_channel.system_append_types::AppendPromptSource, PromptChannelKind,
  SystemPromptAssemblyReceipt (POS: Types and models for system prompt strong append channel suite.)
-
  agent.context_management.system_append_channel.system_prompt_append_suite::SystemPromptStrongAppendChannelSuite
  (POS: Suite managing top-priority system prompt append injection and anti-drift verification.)

[OUTPUT]
- Re-exports: AppendPromptSource, PromptChannelKind, SystemPromptAppendLoader, SystemPromptAssemblyReceipt,
  SystemPromptStrongAppendChannelSuite

[POS]
System prompt strong append channel package.
"""

from __future__ import annotations

from .system_append_loader import SystemPromptAppendLoader
from .system_append_types import (
    AppendPromptSource,
    PromptChannelKind,
    SystemPromptAssemblyReceipt,
)
from .system_prompt_append_suite import (
    SystemPromptStrongAppendChannelSuite,
)

__all__ = [
    "AppendPromptSource",
    "PromptChannelKind",
    "SystemPromptAppendLoader",
    "SystemPromptAssemblyReceipt",
    "SystemPromptStrongAppendChannelSuite",
]
