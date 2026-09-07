"""Transparent large content spillover engine.

Protects LLM context window against 'context bombs' by offloading oversized
user messages or external payloads into safe workspace files while injecting
compact semantic pointers for on-demand inspection.

[INPUT]
- .types: SpilloverConfig, SpilloverPayload, SpilloverResult
- hashlib, uuid, time, os, pathlib

[OUTPUT]
- TransparentSpilloverEngine: Core engine to evaluate, persist, and assemble spillover payloads.

[POS]
Harness context management subsystem protecting against context length explosions.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.agent.context_management.spillover.types import (
    SpilloverConfig,
    SpilloverPayload,
    SpilloverResult,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class TransparentSpilloverEngine:
    """Evaluates message sizes and transparently offloads oversized text to workspace files."""

    def __init__(self, config: SpilloverConfig | None = None) -> None:
        self.config = config or SpilloverConfig()

    def spill_if_oversized(
        self,
        content: str,
        workspace_dir: Path | str,
        session_id: str | None = None,
    ) -> SpilloverResult:
        """Evaluate text length and transparently spill to workspace file if oversized."""
        total_chars = len(content)
        if total_chars <= self.config.max_chars:
            return SpilloverResult(
                is_spilled=False,
                original_chars=total_chars,
                transformed_content=content,
            )

        ws_path = Path(workspace_dir).resolve()
        spillover_dir = ws_path / self.config.spillover_dir_name
        
        # Ensure secure directory creation with restricted POSIX permissions (0o700)
        spillover_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(spillover_dir, 0o700)
        except OSError:
            pass

        now = time.time()
        file_id = uuid4().hex[:10]
        sess_prefix = f"sess_{session_id[:8]}_" if session_id else ""
        filename = f"payload_{sess_prefix}{file_id}.md"
        target_file = spillover_dir / filename
        relative_path = target_file.relative_to(ws_path).as_posix()

        # Compute metadata
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        lines = content.count("\n") + 1
        head_preview = content[: self.config.summary_head_chars].strip()
        tail_preview = content[-self.config.summary_tail_chars :].strip() if total_chars > self.config.summary_head_chars else ""

        # Atomic file write
        temp_file = target_file.with_suffix(".tmp")
        temp_file.write_text(content, encoding="utf-8")
        try:
            os.chmod(temp_file, 0o600)
        except OSError:
            pass
        temp_file.replace(target_file)

        logger.info(
            "TransparentSpilloverEngine offloaded oversized text: %d chars -> %s (sha256=%s)",
            total_chars,
            relative_path,
            sha256[:12],
        )

        payload = SpilloverPayload(
            file_path=str(target_file),
            relative_path=relative_path,
            total_chars=total_chars,
            total_lines=lines,
            sha256_digest=sha256,
            head_preview=head_preview,
            tail_preview=tail_preview,
            created_at=now,
        )

        system_guide = (
            f"\n\n[System Notice: The incoming user message was oversized ({total_chars:,} chars, {lines:,} lines). "
            f"To protect your context window and preserve reasoning quality, the complete content has been safely "
            f"persisted to the workspace file: `{relative_path}`.\n"
            f"--- Preview of Beginning ---\n{head_preview}\n"
            f"---\n"
            f"Whenever you need to inspect specific sections, data points, or complete text, please call `read_file` "
            f"(with optional offset/limit) on `{relative_path}`.]"
        )

        transformed_content = (
            f"<file_spillover path=\"{relative_path}\" chars=\"{total_chars}\" lines=\"{lines}\" digest=\"{sha256[:16]}\" />\n"
            f"{system_guide}"
        )

        return SpilloverResult(
            is_spilled=True,
            original_chars=total_chars,
            transformed_content=transformed_content,
            payload=payload,
            system_guide_prompt=system_guide,
        )
