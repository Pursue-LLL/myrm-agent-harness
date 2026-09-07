from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.agent.context_guard.types import (
    ContextGuardConfig,
    SpilloverPayload,
    SpilloverResult,
    estimate_token_pressure,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class SpilloverEngine:
    """Detects message body overflow and transparently writes payloads to local disk."""

    def __init__(self, config: ContextGuardConfig | None = None) -> None:
        self.config = config or ContextGuardConfig()

    def process_content(
        self,
        content: str | list[dict[str, object] | str] | dict[str, object],
        *,
        base_dir: Path | str,
        role: str = "user",
        custom_prefix: str = "payload",
        session_id: str | None = None,
    ) -> SpilloverResult:
        """Evaluate message length and adaptive token pressure.

        Spills to workspace disk if character cap OR token pressure cap is breached.
        """
        raw_text = self._extract_text(content)
        char_count = len(raw_text)
        token_pressure = estimate_token_pressure(raw_text)

        if (
            char_count <= self.config.max_message_chars
            and token_pressure <= self.config.max_token_pressure
        ):
            return SpilloverResult(
                spilled=False,
                sanitized_content=raw_text,
                original_char_count=char_count,
                estimated_tokens=token_pressure,
            )

        # Content exceeds threshold -> create atomic, concurrency-safe spillover file
        root_path = Path(base_dir).expanduser().resolve()
        spillover_dir = root_path / self.config.spillover_dir_name
        spillover_dir.mkdir(parents=True, exist_ok=True)

        # Enforce POSIX 0o700 directory permissions
        with contextlib.suppress(OSError):
            spillover_dir.chmod(0o700)

        sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        spill_id = f"{custom_prefix}_{sha256[:10]}"
        file_name = f"{spill_id}.md"
        target_file = spillover_dir / file_name

        # Anti-directory-traversal verification
        try:
            target_file.resolve().relative_to(spillover_dir.resolve())
        except ValueError as err:
            logger.error(
                "Security violation: spillover target escaped directory: %s",
                target_file,
            )
            raise PermissionError(
                "Path traversal detected in spillover target file"
            ) from err

        lines = raw_text.count("\n") + 1
        preview = raw_text[: self.config.preview_chars].strip()

        # Atomic, race-condition safe file write with unique temp suffix
        unique_tmp = spillover_dir / f".tmp_{spill_id}_{uuid4().hex[:6]}"
        try:
            unique_tmp.write_text(raw_text, encoding="utf-8")
            with contextlib.suppress(OSError):
                unique_tmp.chmod(0o600)
            unique_tmp.replace(target_file)
        finally:
            if unique_tmp.exists():
                with contextlib.suppress(OSError):
                    unique_tmp.unlink(missing_ok=True)

        logger.info(
            "Context bomb mitigated: spilled %d chars (~%d tokens) into %s (sha256=%s)",
            char_count,
            token_pressure,
            target_file,
            sha256[:8],
        )

        try:
            relative_path = str(target_file.relative_to(root_path))
        except ValueError:
            relative_path = str(target_file)

        # Generate transparent, deterministic XML reference instruction prompt
        sanitized_content = (
            f'<file_spillover path="{relative_path}" chars="{char_count}" lines="{lines}" digest="{sha256[:16]}">\n'
            f"<preview>\n{preview}\n...\n</preview>\n"
            f"<instruction>\n"
            f"Notice: The {role} provided a large document payload ({char_count:,} characters, ~{token_pressure:,} tokens) "
            f"that exceeds the direct context threshold.\n"
            f"It has been safely preserved at '{relative_path}'.\n"
            f"When detailed analysis, code inspection, or specific section retrieval is required, use the 'read_file' tool to inspect this file.\n"
            f"</instruction>\n"
            f"</file_spillover>"
        )

        payload = SpilloverPayload(
            spill_id=spill_id,
            file_path=str(target_file),
            relative_path=relative_path,
            char_count=char_count,
            line_count=lines,
            estimated_tokens=token_pressure,
            sha256_digest=sha256,
            summary_preview=preview,
            original_role=role,
        )

        return SpilloverResult(
            spilled=True,
            sanitized_content=sanitized_content,
            payload=payload,
            original_char_count=char_count,
            estimated_tokens=token_pressure,
        )

    @staticmethod
    def _extract_text(
        content: str | list[dict[str, object] | str] | dict[str, object] | object,
    ) -> str:
        """Extract plain text string from str, list, or dict structures."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text" and "text" in item:
                        parts.append(str(item["text"]))
                    elif "content" in item and isinstance(item["content"], str):
                        parts.append(item["content"])
            return "\n".join(parts)
        if isinstance(content, dict):
            if "text" in content and isinstance(content["text"], str):
                return content["text"]
            if "content" in content and isinstance(content["content"], str):
                return content["content"]
        return ""
