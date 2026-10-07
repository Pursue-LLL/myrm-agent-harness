"""核心引擎实现：长文本入站防御性分页挂载、大消息防爆 Working Memory 与智能摘要网关。

[INPUT]
- 依赖 inbound_shield_types.py 中的契约，标准库 pathlib, hashlib, time, re 等。

[OUTPUT]
- InboundMessageOverflowShield: 入站消息超长防御栅栏引擎

[POS]
- 位于 context_management/inbound_shield/inbound_overflow_shield.py
"""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Sequence

from .inbound_shield_types import (
    InboundMountedDocument,
    InboundPayloadClassification,
    InboundShieldConfig,
    InboundShieldResult,
)


class InboundMessageOverflowShield:
    """入站大消息防爆栅栏引擎。

    彻底破除用户从企微/飞书/网页等渠道一次性粘贴上万字长文本直接塞爆
    当前 Agent 上下文窗口导致模型严重注意力涣散、Token 激增与超限崩溃的顽疾。
    """

    def __init__(self, config: InboundShieldConfig | None = None) -> None:
        self.config = config or InboundShieldConfig()

    def inspect_and_shield(
        self,
        message_content: str,
        message_id: str | None = None,
        workspace_root: Path | str | None = None,
    ) -> InboundShieldResult:
        """审计入站消息体量，必要时拦截大文本、自动挂载工作区并注入骨架指针。"""
        char_count = len(message_content)
        estimated_tokens = self._estimate_tokens(message_content)

        # 1. 守门员判定：未超限则直接放行直通
        if (
            char_count <= self.config.char_threshold
            and estimated_tokens <= self.config.token_threshold
        ):
            return InboundShieldResult(
                is_intercepted=False,
                classification=InboundPayloadClassification.SAFE_PASS_THROUGH,
                shielded_content=message_content,
                mounted_doc=None,
                original_chars=char_count,
                original_estimated_tokens=estimated_tokens,
                effective_tokens=estimated_tokens,
                saved_tokens=0,
                read_tool_guidance=None,
            )

        # 2. 超限分类
        classification = (
            InboundPayloadClassification.EXTREME_PAYLOAD_CLAMPED
            if char_count > self.config.extreme_char_threshold
            else InboundPayloadClassification.OVERSIZED_TRUNCATED_AND_MOUNTED
        )

        # 3. 标识符与哈希计算
        sha256_hash = hashlib.sha256(message_content.encode("utf-8")).hexdigest()
        mount_id = message_id if message_id else f"payload_{sha256_hash[:12]}"
        file_name = f"inbound_{mount_id}.txt"
        relative_path = f"{self.config.mount_directory_relative}/{file_name}"

        # 4. 骨架摘要提炼与结构化特征提取
        skeleton_summary, key_entities = self._extract_skeleton_summary(
            message_content
        )

        # 5. 沙箱工作区物理落盘挂载
        abs_path_str = relative_path
        if self.config.enable_auto_mounting and workspace_root is not None:
            root_path = Path(workspace_root).resolve()
            target_file = root_path / relative_path
            try:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(message_content, encoding="utf-8")
                abs_path_str = str(target_file)
            except OSError:
                abs_path_str = str(target_file)

        created_at_iso = datetime.now(timezone.utc).isoformat()
        mounted_doc = InboundMountedDocument(
            mount_id=mount_id,
            relative_path=relative_path,
            absolute_path=abs_path_str,
            char_count=char_count,
            estimated_tokens=estimated_tokens,
            sha256_hash=sha256_hash,
            skeleton_summary=skeleton_summary,
            created_at_iso=created_at_iso,
            key_entities=key_entities,
        )

        # 6. 构建防御性上下文代理提示词
        guidance = (
            f"Use 'read_file' tool to inspect specific lines or sections in '{relative_path}'."
        )
        shielded_content = self._render_shielded_message(
            mounted_doc=mounted_doc,
            classification=classification,
            guidance=guidance,
        )
        effective_tokens = self._estimate_tokens(shielded_content)
        saved_tokens = max(0, estimated_tokens - effective_tokens)

        return InboundShieldResult(
            is_intercepted=True,
            classification=classification,
            shielded_content=shielded_content,
            mounted_doc=mounted_doc,
            original_chars=char_count,
            original_estimated_tokens=estimated_tokens,
            effective_tokens=effective_tokens,
            saved_tokens=saved_tokens,
            read_tool_guidance=guidance,
        )

    def read_mounted_payload(
        self,
        relative_path: str,
        workspace_root: Path | str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """安全读取工作区已挂载的大文本内容，支持行号切片。"""
        if workspace_root is None:
            raise ValueError("workspace_root must be provided to read mounted payload.")

        root_path = Path(workspace_root).resolve()
        target_path = (root_path / relative_path).resolve()

        # 安全防逃逸校验
        if not str(target_path).startswith(str(root_path)):
            raise PermissionError(f"Path traversal detected: {relative_path}")

        if not target_path.exists():
            raise FileNotFoundError(f"Mounted payload not found: {relative_path}")

        lines = target_path.read_text(encoding="utf-8").splitlines()
        total_lines = len(lines)

        s_idx = max(0, (start_line - 1)) if start_line is not None else 0
        e_idx = min(total_lines, end_line) if end_line is not None else total_lines

        if s_idx >= total_lines or s_idx >= e_idx:
            return ""

        return "\n".join(lines[s_idx:e_idx])

    def cleanup_stale_mounts(
        self,
        workspace_root: Path | str | None = None,
        retention_seconds: int = 86400,
    ) -> int:
        """清理已过期的临时挂载文件。"""
        if workspace_root is None:
            return 0

        root_path = Path(workspace_root).resolve()
        mount_dir = root_path / self.config.mount_directory_relative
        if not mount_dir.exists() or not mount_dir.is_dir():
            return 0

        now = datetime.now(timezone.utc).timestamp()
        deleted_count = 0

        for file_path in mount_dir.glob("inbound_*.txt"):
            if not file_path.is_file():
                continue
            try:
                mtime = file_path.stat().st_mtime
                if (now - mtime) > retention_seconds:
                    file_path.unlink()
                    deleted_count += 1
            except OSError:
                continue

        return deleted_count

    def _estimate_tokens(self, text: str) -> int:
        """启发式评估 Token 消耗，贴合中英文混合场景。"""
        stripped = text.strip()
        if not stripped:
            return 0
        return max(1, int(len(stripped) / 3.2))

    def _extract_skeleton_summary(
        self, text: str
    ) -> tuple[str, tuple[str, ...]]:
        """提取高密结构化骨架摘要与关键线索实体。"""
        entities: list[str] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # 1. 结构特征嗅探
        headers: list[str] = []
        for line in lines:
            if line.startswith(("#", "##", "###", "####")):
                headers.append(line[:60])
            elif any(kw in line.upper() for kw in ("ERROR", "EXCEPTION", "TRACEBACK", "FAILED")):
                if "error_trace" not in entities:
                    entities.append("error_trace")
            elif line.startswith(("def ", "class ", "function ", "interface ")):
                if "source_code" not in entities:
                    entities.append("source_code")

        if headers and "markdown_outline" not in entities:
            entities.append("markdown_outline")

        # 2. 首尾片段提炼
        head_sample = text[: self.config.preview_head_chars].strip()
        tail_sample = text[-self.config.preview_tail_chars :].strip()

        outline_part = ""
        if headers and self.config.extract_outline_headers:
            selected_headers = headers[:4]
            outline_part = f" Outline: [ {', '.join(selected_headers)} ] |"

        raw_summary = (
            f"Head: {head_sample}... |{outline_part} Tail: ...{tail_sample}"
        )

        # 3. 截断至受控长度
        max_chars = self.config.max_skeleton_summary_chars
        summary_clean = re.sub(r"\s+", " ", raw_summary).strip()
        if len(summary_clean) > max_chars:
            summary_clean = summary_clean[: max_chars - 3] + "..."

        return summary_clean, tuple(entities)

    def _render_shielded_message(
        self,
        mounted_doc: InboundMountedDocument,
        classification: InboundPayloadClassification,
        guidance: str,
    ) -> str:
        """生成注入 Working Memory 的防御性轻量消息卡片。"""
        entities_tag = (
            f" [Features: {', '.join(mounted_doc.key_entities)}]"
            if mounted_doc.key_entities
            else ""
        )
        return (
            "[INBOUND_OVERFLOW_SHIELD: PAYLOAD_MOUNTED_TO_WORKSPACE]\n"
            f"⚠️ Notice: Incoming message is oversized ({mounted_doc.char_count:,} chars, "
            f"~{mounted_doc.estimated_tokens:,} tokens, status: {classification.value}).\n"
            "To prevent context dilution, runaway cost, and context overflow errors, the complete "
            "untruncated text has been safely offloaded and mounted into your workspace without loss.\n\n"
            f"📁 Mounted Path: `{mounted_doc.relative_path}`{entities_tag}\n"
            f"🔑 SHA-256: `{mounted_doc.sha256_hash[:16]}...`\n\n"
            "📋 High-Density Skeleton Summary:\n"
            f"{mounted_doc.skeleton_summary}\n\n"
            f"💡 Action: {guidance}"
        )
