from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.agent.context_guard.types import (
    ContextGuardConfig,
    SpilloverPayload,
    SpilloverResult,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class SpilloverEngine:
    """Detects message body overflow and transparently writes payloads to local disk."""

    def __init__(self, config: ContextGuardConfig | None = None) -> None:
        self.config = config or ContextGuardConfig()

    def process_content(
        self,
        content: str,
        *,
        base_dir: Path | str,
        role: str = "user",
        custom_prefix: str = "payload",
    ) -> SpilloverResult:
        """Evaluate message length and spill to disk if it exceeds safety threshold."""
        char_count = len(content)
        if char_count <= self.config.max_message_chars:
            return SpilloverResult(
                spilled=False,
                sanitized_content=content,
                original_char_count=char_count,
            )

        # Content exceeds threshold -> create atomic spillover file
        root_path = Path(base_dir).expanduser().resolve()
        spillover_dir = root_path / self.config.spillover_dir_name
        spillover_dir.mkdir(parents=True, exist_ok=True)

        # Set secure directory permissions if POSIX
        try:
            spillover_dir.chmod(0o700)
        except OSError:
            pass

        spill_id = f"{custom_prefix}_{uuid4().hex[:8]}"
        file_name = f"{spill_id}.md"
        target_file = spillover_dir / file_name

        # Calculate metrics
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        lines = content.count("\n") + 1
        preview = content[: self.config.preview_chars].strip()

        # Atomic file write
        temp_file = target_file.with_suffix(".tmp")
        temp_file.write_text(content, encoding="utf-8")
        try:
            temp_file.chmod(0o600)
        except OSError:
            pass
        temp_file.replace(target_file)

        logger.info(
            "Context bomb mitigated: spilled %d chars into %s (sha256=%s)",
            char_count,
            target_file,
            sha256[:8],
        )

        relative_or_abs_path = str(target_file)

        # Generate transparent file reference instruction prompt
        sanitized_content = (
            f"[System Notice: The {role} provided an extensive document/payload consisting of {char_count:,} characters "
            f"({lines:,} lines). To protect the LLM context window from being flooded, the full content has been securely "
            f"spilled to disk at: `{relative_or_abs_path}` (SHA-256: `{sha256}`).\n\n"
            f"### Content Preview (First {len(preview)} chars):\n"
            f"```text\n{preview}\n...\n```\n\n"
            f"If you need to analyze, inspect, or process specific sections or the entire text, please use your `read_file` "
            f"or bash tools to inspect `{relative_or_abs_path}`.]"
        )

        payload = SpilloverPayload(
            spill_id=spill_id,
            file_path=relative_or_abs_path,
            char_count=char_count,
            line_count=lines,
            sha256_digest=sha256,
            summary_preview=preview,
            original_role=role,
        )

        return SpilloverResult(
            spilled=True,
            sanitized_content=sanitized_content,
            payload=payload,
            original_char_count=char_count,
        )
