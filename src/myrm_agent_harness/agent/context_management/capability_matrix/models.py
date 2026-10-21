"""[INPUT]
- None (pure domain models)

[OUTPUT]
- CommandCategory: Capability domain categories
- CommandMatrixEntry: Individual system command specification
- ContextStateSnapshot: Current session runtime state indicators
- CapabilityHintChip: Context-aware progressive recommendation chip

[POS]
Harness framework layer contracts for Context-Aware Capability Discovery & Interactive Command Matrix (Item 38 P0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CommandCategory = Literal[
    "concurrency_collaboration",  # 并发协作 (/bg, /btw, /steer, /fork)
    "data_science",               # 数据与科学 (/pykernel, /repl, /chart, /data-diff)
    "security_credential",        # 安全与凭证 (/vault, /secret, /sandbox)
    "memory_knowledge",           # 记忆与知识 (/recall, /memory, /pin, /tag)
    "delivery_workflow",          # 办公与交付 (/sop, /export, /timeline, /scratchpad)
]


@dataclass(slots=True)
class CommandMatrixEntry:
    command: str
    category: CommandCategory
    title_zh: str
    title_en: str
    description_zh: str
    description_en: str
    shortcut: str | None = None
    prompt_template: str = ""
    tags: list[str] = field(default_factory=list)
    requires_running_task: bool = False


@dataclass(slots=True)
class ContextStateSnapshot:
    session_id: str
    status: Literal["idle", "running", "paused", "interrupted", "error"] = "idle"
    running_step_count: int = 0
    recent_tools: list[str] = field(default_factory=list)
    user_prompt_focused: bool = False
    mastered_commands: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CapabilityHintChip:
    chip_id: str
    command: str
    label_zh: str
    label_en: str
    reason_zh: str
    reason_en: str
    priority: int = 1
    insert_prompt: str = ""
