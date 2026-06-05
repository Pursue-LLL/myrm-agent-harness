"""Session Notes 后台异步更新器

[INPUT]
- schemas::SessionNotes, SessionNotesConfig (POS: 笔记数据结构)
- prompts::build_incremental_prompt, build_full_refresh_prompt (POS: 提示词模板)
- trigger::SessionNotesTrigger (POS: 触发策略)
- langchain_core.language_models::BaseChatModel (POS: LLM 基类)
- langchain_core.messages::BaseMessage, HumanMessage (POS: 消息类型)

[OUTPUT]
- SessionNotesManager: 后台异步更新管理器
- NotesPersistCallback: 笔记持久化回调类型
- NotesLoadCallback: 笔记加载回调类型

[POS]
Session Notes core update engine. Manages the async update lifecycle: incremental merges, periodic full refreshes (preventing information drift), trailing-run mode, and circuit breaker for consecutive failures.

"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from myrm_agent_harness.observability.metrics.circuit_breaker_metrics import (
    circuit_breaker_failures_total,
    circuit_breaker_state,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .prompts import build_full_refresh_prompt, build_incremental_prompt
from .schemas import SessionNotes, SessionNotesConfig
from .trigger import SessionNotesTrigger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage

logger = get_agent_logger(__name__)

NotesPersistCallback = Callable[[str], Awaitable[None]]
"""(notes_json: str) -> None — 将笔记 JSON 持久化到 DB"""

NotesLoadCallback = Callable[[], Awaitable[str | None]]
"""() -> notes_json | None — 从 DB 加载笔记 JSON"""


class SessionNotesManager:
    """Session Notes 后台异步更新管理器

    核心设计：
    1. 尾随运行：正在更新时新请求只记录待处理上下文，完成后自动再跑一次
    2. 增量合并 + 定期全量刷新：每 N 次增量后做一次全量重建
    3. 断路器：连续失败 N 次后停止尝试
    4. 等待机制：压缩时可等待进行中的更新完成
    """

    def __init__(
        self,
        llm: BaseChatModel,
        config: SessionNotesConfig | None = None,
        on_persist: NotesPersistCallback | None = None,
    ) -> None:
        self._llm = llm
        self._config = config or SessionNotesConfig()
        self._notes = SessionNotes(config=self._config)
        self._trigger = SessionNotesTrigger(self._config)
        self._on_persist = on_persist

        self._updating = False
        self._update_done = asyncio.Event()
        self._update_done.set()
        self._update_task: asyncio.Task[None] | None = None

        self._pending_messages: list[BaseMessage] | None = None
        self._pending_message_idx: int = 0

        self._consecutive_failures = 0
        self._circuit_open_time: float = 0.0

    @property
    def notes(self) -> SessionNotes:
        return self._notes

    @property
    def trigger(self) -> SessionNotesTrigger:
        return self._trigger

    @property
    def is_updating(self) -> bool:
        return self._updating

    def _is_circuit_open(self) -> bool:
        """检查熔断器状态，并在冷却时间结束后自动恢复"""
        if self._consecutive_failures < self._config.max_consecutive_failures:
            return False

        if self._circuit_open_time > 0:
            elapsed = time.time() - self._circuit_open_time
            if elapsed > self._config.circuit_breaker_cooldown_seconds:
                logger.warning(
                    " [SessionNotes] Circuit breaker auto-recovery after %d seconds — resetting state", int(elapsed)
                )
                self._consecutive_failures = 0
                self._circuit_open_time = 0.0
                circuit_breaker_state.labels(component="session_notes").set(0)  # CLOSED
                return False

        return True

    def load_from_json(self, json_str: str) -> None:
        """从 JSON 加载笔记（会话恢复时从 DB 加载）"""
        self._notes = SessionNotes.from_json(json_str, self._config)
        logger.warning(" [SessionNotes] Loaded notes from DB")

    async def maybe_trigger_update(self, messages: list[BaseMessage], total_tokens: int, total_tool_calls: int) -> None:
        """检查是否应该触发更新，如果是则异步启动

        在 context_pipeline_middleware 中每次 API 调用前调用。
        """
        if self._is_circuit_open():
            return

        if not self._trigger.should_update(messages, total_tokens, total_tool_calls):
            return

        message_idx = len(messages)
        if self._updating:
            self._pending_messages = list(messages)
            self._pending_message_idx = message_idx
            logger.warning(" [SessionNotes] Update in progress, queued trailing run")
            return

        self._update_task = asyncio.create_task(self._run_update(messages, message_idx))

    async def wait_for_update(self) -> None:
        """等待进行中的更新完成（带超时）

        在 SessionNotesProcessor 中调用，确保压缩时用最新笔记。
        """
        if not self._updating:
            return
        try:
            await asyncio.wait_for(self._update_done.wait(), timeout=self._config.wait_timeout_seconds)
        except TimeoutError:
            logger.warning(
                " [SessionNotes] Wait timed out after %.1fs, using current version", self._config.wait_timeout_seconds
            )

    async def _run_update(self, messages: list[BaseMessage], message_idx: int) -> None:
        """执行一次更新（增量或全量）+ 尾随运行"""
        self._updating = True
        self._update_done.clear()

        try:
            await self._do_update(messages, message_idx)
            self._consecutive_failures = 0
        except Exception as exc:
            from myrm_agent_harness.observability.auth_detector import detect_auth_failure, get_auth_error_hint

            if detect_auth_failure(exc):
                self._consecutive_failures = self._config.max_consecutive_failures
                self._circuit_open_time = time.time()
                auth_hint = get_auth_error_hint(exc)
                logger.error(
                    " [SessionNotes] Auth failure detected — circuit breaker opened | %s: %s | Hint: %s",
                    type(exc).__name__,
                    exc,
                    auth_hint,
                )
                circuit_breaker_failures_total.labels(component="session_notes", error_type="auth").inc()
                circuit_breaker_state.labels(component="session_notes").set(2)  # OPEN
            else:
                self._consecutive_failures += 1
                error_type = "timeout" if "timeout" in str(exc).lower() else "other"
                circuit_breaker_failures_total.labels(component="session_notes", error_type=error_type).inc()

                if self._consecutive_failures >= self._config.max_consecutive_failures:
                    self._circuit_open_time = time.time()
                    circuit_breaker_state.labels(component="session_notes").set(2)  # OPEN
                    logger.warning(
                        " [SessionNotes] Circuit breaker tripped after %d consecutive failures — "
                        "stopping future attempts | last error: %s: %s",
                        self._consecutive_failures,
                        type(exc).__name__,
                        exc,
                    )
                else:
                    logger.warning(
                        " [SessionNotes] Update failed (%d/%d) | %s: %s",
                        self._consecutive_failures,
                        self._config.max_consecutive_failures,
                        type(exc).__name__,
                        exc,
                    )
        finally:
            pending = self._pending_messages
            pending_idx = self._pending_message_idx
            self._pending_messages = None

            if pending is not None and self._consecutive_failures < self._config.max_consecutive_failures:
                logger.warning(" [SessionNotes] Running trailing update")
                try:
                    await self._do_update(pending, pending_idx)
                    self._consecutive_failures = 0
                except Exception as exc:
                    from myrm_agent_harness.observability.auth_detector import (
                        detect_auth_failure,
                        get_auth_error_hint,
                    )

                    if detect_auth_failure(exc):
                        self._consecutive_failures = self._config.max_consecutive_failures
                        self._circuit_open_time = time.time()
                        auth_hint = get_auth_error_hint(exc)
                        logger.error(
                            " [SessionNotes] Trailing update - Auth failure detected | %s: %s | Hint: %s",
                            type(exc).__name__,
                            exc,
                            auth_hint,
                        )
                        circuit_breaker_failures_total.labels(component="session_notes", error_type="auth").inc()
                        circuit_breaker_state.labels(component="session_notes").set(2)  # OPEN
                    else:
                        self._consecutive_failures += 1
                        error_type = "timeout" if "timeout" in str(exc).lower() else "other"
                        circuit_breaker_failures_total.labels(component="session_notes", error_type=error_type).inc()

                        if self._consecutive_failures >= self._config.max_consecutive_failures:
                            self._circuit_open_time = time.time()
                            circuit_breaker_state.labels(component="session_notes").set(2)  # OPEN
                        logger.warning(" [SessionNotes] Trailing update failed: %s: %s", type(exc).__name__, exc)

            self._updating = False
            self._update_done.set()

    async def _do_update(self, messages: list[BaseMessage], message_idx: int) -> None:
        """执行实际的笔记更新（增量合并或全量刷新）"""
        from ..summary_parser import format_messages_for_summary

        is_full_refresh = self._notes.needs_full_refresh()

        if is_full_refresh:
            truncated = _truncate_messages_for_update(messages, _MAX_UPDATE_CHARS)
            context_text = format_messages_for_summary(truncated)
            prompt = build_full_refresh_prompt(self._notes, context_text)
            mode = "full refresh"
        else:
            new_messages = messages[self._notes.last_updated_message_idx :]
            if not new_messages:
                logger.warning(" [SessionNotes] No new messages, skipping update")
                return
            truncated = _truncate_messages_for_update(new_messages, _MAX_UPDATE_CHARS)
            context_text = format_messages_for_summary(truncated)
            prompt = build_incremental_prompt(self._notes, context_text)
            mode = "incremental"

        from langchain_core.messages import HumanMessage

        # Explicit empty callbacks to prevent LangGraph's inherited callback context
        # from capturing Session Notes LLM tokens as main conversation stream events.
        # Without this, asyncio.create_task inherits the parent's contextvars and
        # the LLM response leaks into the streaming output queue.
        response = await self._llm.ainvoke([HumanMessage(content=prompt)], config={"callbacks": []})
        content = response.content if isinstance(response.content, str) else str(response.content)

        updated_sections = _parse_notes_response(content)
        if not updated_sections:
            logger.info(
                " [SessionNotes] Failed to parse LLM response, skipping. Response preview: %s",
                content[:150],
            )
            return

        section_map = {s.key: s for s in self._notes.sections}
        updated_keys: list[str] = []
        for key, new_content in updated_sections.items():
            if key in section_map and new_content.strip():
                section_map[key].content = new_content.strip()
                updated_keys.append(key)

        self._notes.last_updated_message_idx = message_idx

        if is_full_refresh:
            self._notes.incremental_count = 0
        else:
            self._notes.incremental_count += 1

        logger.warning(
            " [SessionNotes] Updated (%s): %d sections | total ~%d tokens",
            mode,
            len(updated_keys),
            self._notes.estimate_total_tokens(),
        )

        if self._on_persist is not None:
            try:
                await self._on_persist(self._notes.to_json())
            except Exception as exc:
                logger.warning(" [SessionNotes] Persist callback failed: %s: %s", type(exc).__name__, exc)


_MAX_UPDATE_CHARS = 120_000
"""后台更新时传给轻量级模型的最大字符数（约 30K token）。
防止全量刷新或大量新消息导致轻量级模型 PTL 错误。"""


def _truncate_messages_for_update(messages: list[BaseMessage], max_chars: int) -> list[BaseMessage]:
    """从末尾保留消息，总字符数不超过 max_chars。

    优先保留最近的消息（最新信息对笔记更新最有价值）。
    """
    total = 0
    keep_start = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        content = messages[i].content
        char_count = len(content) if isinstance(content, str) else len(str(content))
        if total + char_count > max_chars:
            break
        total += char_count
        keep_start = i

    return messages[keep_start:]


def _parse_notes_response(content: str) -> dict[str, str] | None:
    """解析 LLM 响应为 section key → content 映射"""
    json_str = _extract_json_block(content)
    if not json_str:
        json_str = content.strip()

    try:
        data = json.loads(json_str)
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _extract_json_block(text: str) -> str | None:
    """从文本中提取 JSON 代码块"""
    start = text.find("```json")
    if start == -1:
        start = text.find("```")
        if start == -1:
            return None
        start = text.find("\n", start)
    else:
        start = text.find("\n", start)

    if start == -1:
        return None

    end = text.find("```", start + 1)
    if end == -1:
        return None

    return text[start:end].strip()
