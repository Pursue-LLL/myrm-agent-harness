# [POS]: myrm_agent_harness.toolkits.memory.failure_retrieval.search_engine
# [INPUT]: models.py (ErrorFingerprint, FailureOutcomeType, HistoricalResolutionEntry, FailureRetrievalResult)
# [OUTPUT]: FailureHistoricalSessionSearchEngine

"""Search engine indexing and retrieving historical session solutions and failures.

P0 delivery for Item 109 in topic_01 memory roadmap.
Supports dual-track matching (successful solutions and cautionary failures)
and direct reading of concrete session solution snippets without guessing.

[INPUT]
- toolkits.memory.failure_retrieval.models::ErrorFingerprint, FailureOutcomeType, FailureRetrievalResult,
  HistoricalResolutionEntry (POS: Domain models for failure-triggered historical session retrieval.)

[OUTPUT]
- FailureHistoricalSessionSearchEngine: Indexes historical session resolutions and provides dual-track
  similarity search.

[POS]
Search engine indexing and retrieving historical session solutions and failures.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.failure_retrieval.models import (
    ErrorFingerprint,
    FailureOutcomeType,
    FailureRetrievalResult,
    HistoricalResolutionEntry,
)

logger = logging.getLogger(__name__)


class FailureHistoricalSessionSearchEngine:
    """Indexes historical session resolutions and provides dual-track similarity search."""

    def __init__(self, initial_entries: list[HistoricalResolutionEntry] | None = None) -> None:
        self._entries: dict[str, HistoricalResolutionEntry] = {}
        if initial_entries:
            for e in initial_entries:
                self.index_resolution(e)
        else:
            self._seed_default_resolutions()

    def _seed_default_resolutions(self) -> None:
        """Seed industrial baseline resolutions for common recurring operational errors."""
        seeds = [
            # 1. Git branch push rejected
            HistoricalResolutionEntry(
                entry_id="hist_git_push_01",
                session_id="sess_git_reject_20260901",
                turn_index=4,
                error_signature="PermissionDeniedError git push rejected by pre-receive hook branch protected",
                outcome_type=FailureOutcomeType.SUCCESSFUL_RESOLUTION,
                solution_snippet="git checkout -b feat/fix-branch && git push -u origin feat/fix-branch",
                explanation="直接向 main 分支推送触发了只读保护，切换到特性分支并推送 PR 顺利合入。",
                confidence=1.0,
            ),
            # 2. Port already in use (Dead-end cautionary failure)
            HistoricalResolutionEntry(
                entry_id="hist_port_fail_02",
                session_id="sess_port_loop_20260903",
                turn_index=2,
                error_signature="PortAlreadyInUseError address already in use <ADDR> port",
                outcome_type=FailureOutcomeType.CAUTIONARY_FAILURE,
                solution_snippet="sleep 5 && retry_start_server",
                explanation="直接 sleep 重试依然报错，因为孤儿进程占用了端口，必须显式释放端口或杀死孤儿进程。",
                confidence=0.9,
            ),
            # 3. Port already in use (Successful resolution)
            HistoricalResolutionEntry(
                entry_id="hist_port_success_03",
                session_id="sess_port_resolved_20260903",
                turn_index=5,
                error_signature="PortAlreadyInUseError address already in use <ADDR> port",
                outcome_type=FailureOutcomeType.SUCCESSFUL_RESOLUTION,
                solution_snippet="lsof -ti:8000 | xargs kill -9 && start_server",
                explanation="使用 lsof 找出占用 8000 端口的残留进程并强制清理后，服务一次性成功启动。",
                confidence=0.98,
            ),
            # 4. Database deadlock or lock timeout
            HistoricalResolutionEntry(
                entry_id="hist_db_lock_04",
                session_id="sess_pg_lock_20260908",
                turn_index=6,
                error_signature="DatabaseLockTimeout deadlock detected on relation migration",
                outcome_type=FailureOutcomeType.SUCCESSFUL_RESOLUTION,
                solution_snippet="CREATE INDEX CONCURRENTLY idx_users_email ON users(email);",
                explanation="生产大表加索引导致排他锁超时，改用 CONCURRENTLY 选项避免全表死锁。",
                confidence=0.95,
            ),
            # 5. Connection refused / service not ready
            HistoricalResolutionEntry(
                entry_id="hist_conn_refuse_05",
                session_id="sess_docker_ready_20260912",
                turn_index=3,
                error_signature="ConnectionRefusedError connect: connection refused redis",
                outcome_type=FailureOutcomeType.SUCCESSFUL_RESOLUTION,
                solution_snippet="docker inspect -f '{{.State.Health.Status}}' redis_container && wait-for-it localhost:6379",
                explanation="容器启动阶段健康检查尚未通过，等待健康探测变为 healthy 后再发起客户端连接。",
                confidence=0.92,
            ),
        ]
        for s in seeds:
            self.index_resolution(s)

    def index_resolution(self, entry: HistoricalResolutionEntry) -> None:
        """Add or update a historical resolution entry."""
        self._entries[entry.entry_id] = entry

    def list_entries(self) -> list[HistoricalResolutionEntry]:
        """List all indexed historical resolution entries."""
        return list(self._entries.values())

    def read_session_resolution(
        self, session_id: str, turn_index: int | None = None
    ) -> HistoricalResolutionEntry | None:
        """Directly read historical solution from session without guessing."""
        for entry in self._entries.values():
            if entry.session_id == session_id and (turn_index is None or entry.turn_index == turn_index):
                return entry
        return None

    def search(
        self,
        fingerprint: ErrorFingerprint,
        top_n: int = 3,
        include_cautionary: bool = True,
    ) -> FailureRetrievalResult:
        """Search historical sessions for matching error signatures.

        Performs dual-track classification returning both successful fixes
        and cautionary dead ends to prevent repeating futile attempts.
        """
        query_text = f"{fingerprint.error_type} {fingerprint.normalized_pattern} {' '.join(fingerprint.context_tags)}".lower()
        scored_entries: list[tuple[float, HistoricalResolutionEntry]] = []

        for entry in self._entries.values():
            score = self._compute_similarity(query_text, entry.error_signature.lower())
            if score > 0.15:  # Relevance cutoff
                scored_entries.append((score, entry))

        # Sort by similarity score descending
        scored_entries.sort(key=lambda x: x[0], reverse=True)

        successful_matches: list[HistoricalResolutionEntry] = []
        cautionary_matches: list[HistoricalResolutionEntry] = []

        for _, entry in scored_entries:
            if entry.outcome_type == FailureOutcomeType.SUCCESSFUL_RESOLUTION and len(successful_matches) < top_n:
                successful_matches.append(entry)
            elif include_cautionary and entry.outcome_type == FailureOutcomeType.CAUTIONARY_FAILURE and len(cautionary_matches) < top_n:
                cautionary_matches.append(entry)

        # Synthesize recommendation
        suggested = ""
        if successful_matches:
            best = successful_matches[0]
            suggested = f"历史会话 [{best.session_id}] 曾成功解决同类错误: {best.solution_snippet} ({best.explanation})"
        elif cautionary_matches:
            worst = cautionary_matches[0]
            suggested = f"警告：历史会话 [{worst.session_id}] 曾尝试以下路径并失败: {worst.solution_snippet}，请避免重复该踩坑路径。"

        total = len(successful_matches) + len(cautionary_matches)
        return FailureRetrievalResult(
            query_fingerprint=fingerprint,
            total_matched=total,
            successful_resolutions=successful_matches,
            cautionary_failures=cautionary_matches,
            suggested_action=suggested,
        )

    def _compute_similarity(self, query: str, signature: str) -> float:
        """Compute keyword and token overlap ratio between query and error signature."""
        query_tokens = set(query.split())
        sig_tokens = set(signature.split())
        if not query_tokens or not sig_tokens:
            return 0.0

        intersection = query_tokens.intersection(sig_tokens)
        return len(intersection) / len(sig_tokens)
