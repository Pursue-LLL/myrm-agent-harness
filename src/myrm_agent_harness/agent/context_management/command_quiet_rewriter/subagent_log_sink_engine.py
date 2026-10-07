"""Subagent Log Sink Engine that absorbs massive process outputs into isolated contexts.

Implements the blackhole quarantine pattern: voluminous logs and batch test outputs
stay trapped within disposable subagent execution contexts, while only a concise,
structured 3-5 line conclusion card is delivered back to the main session.
"""

from __future__ import annotations

import re
import time
import uuid

from .quiet_rewriter_types import (
    LogSinkConclusionCard,
    LogSinkStatus,
    LogSinkTaskSpec,
    LogSinkTaskType,
    SubagentLogSinkExecutionRecord,
)


class SubagentLogSinkEngine:
    """Quarantines verbose outputs in disposable subagent sandboxes and distills key signals."""

    # Patterns for test summary parsing (pytest, vitest, jest)
    _PYTEST_SUMMARY_PATTERN = re.compile(
        r"(?:=+\s*)?(?:(\d+)\s+passed)?(?:,?\s*(\d+)\s+failed)?(?:,?\s*(\d+)\s+error)?(?:,?\s*(\d+)\s+skipped)?.*in\s+([\d\.]+)s",
        re.IGNORECASE,
    )
    _TEST_FAILURE_FILE_PATTERN = re.compile(
        r"(?:FAILED|ERROR)\s+([a-zA-Z0-9_\-\./\\]+\.py::[a-zA-Z0-9_]+)",
        re.IGNORECASE,
    )
    _LOG_ERROR_PATTERN = re.compile(
        r"^(?:.*?(?:ERROR|FATAL|PANIC|CRITICAL|Exception|Traceback).*?)$",
        re.MULTILINE | re.IGNORECASE,
    )

    def distill_and_quarantine(
        self,
        task_spec: LogSinkTaskSpec,
        raw_output: str,
        execution_duration_ms: float = 0.0,
        subagent_steps: int = 1,
    ) -> tuple[LogSinkConclusionCard, SubagentLogSinkExecutionRecord]:
        """Process raw output in quarantine and produce a distilled low-noise conclusion card."""
        start_time = time.monotonic()
        raw_chars = len(raw_output)

        if task_spec.task_type == LogSinkTaskType.BATCH_TEST:
            card = self._distill_batch_test(task_spec, raw_output)
        elif task_spec.task_type == LogSinkTaskType.LOG_ANALYSIS:
            card = self._distill_log_analysis(task_spec, raw_output)
        elif task_spec.task_type == LogSinkTaskType.GIT_HISTORY:
            card = self._distill_git_history(task_spec, raw_output)
        elif task_spec.task_type == LogSinkTaskType.BUILD_INSPECTION:
            card = self._distill_build_inspection(task_spec, raw_output)
        else:
            card = self._distill_generic(task_spec, raw_output)

        elapsed = execution_duration_ms or (time.monotonic() - start_time) * 1000.0

        # Rough token estimation: 1 token ~= 4 characters
        raw_tokens = max(1, raw_chars // 4)
        delivered_tokens = max(1, card.delivered_character_count // 4)

        record = SubagentLogSinkExecutionRecord(
            record_id=f"sink-rec-{uuid.uuid4().hex[:8]}",
            task_spec=task_spec,
            conclusion_card=card,
            subagent_quarantined_messages=subagent_steps * 2,
            raw_tokens_absorbed=raw_tokens,
            delivered_tokens=delivered_tokens,
            duration_ms=elapsed,
        )

        return card, record

    def _distill_batch_test(self, task: LogSinkTaskSpec, output: str) -> LogSinkConclusionCard:
        """Distill large test suite outputs into passes, failures, and fault locations."""
        passed = 0
        failed = 0
        status = LogSinkStatus.SUCCESS
        bullets: list[str] = []
        error_locs: list[str] = []

        # Find pytest / vitest summary lines (e.g. '2 failed, 400 passed in 12.34s')
        for line in output.splitlines():
            if re.search(r"\bin\s+[\d\.]+s\b", line, re.IGNORECASE) or line.strip().startswith("===="):
                m_pass = re.search(r"(\d+)\s+passed\b", line, re.IGNORECASE)
                m_fail = re.search(r"(\d+)\s+failed\b", line, re.IGNORECASE)
                m_err = re.search(r"(\d+)\s+error\b", line, re.IGNORECASE)
                if m_pass or m_fail or m_err:
                    if m_pass:
                        passed = int(m_pass.group(1))
                    if m_fail:
                        failed += int(m_fail.group(1))
                    if m_err:
                        failed += int(m_err.group(1))
                    break

        # Extract failed test locations
        for match in self._TEST_FAILURE_FILE_PATTERN.finditer(output):
            loc = match.group(1).strip()
            if loc not in error_locs:
                error_locs.append(loc)

        total = passed + failed
        if failed > 0:
            status = LogSinkStatus.FAILURE
            bullets.append(f"Completed {total} test cases: {passed} passed, {failed} failed.")
            if error_locs:
                bullets.append(f"Primary failures located in: {', '.join(error_locs[:3])}")
            suggested_action = f"Inspect failing assertions in {error_locs[0] if error_locs else 'reported tests'}."
        elif total > 0:
            status = LogSinkStatus.SUCCESS
            bullets.append(f"All {passed} test cases passed cleanly with 0 failures.")
            suggested_action = None
        else:
            # Fallback for unrecognized test runners
            if "FAIL" in output or "ERROR" in output:
                status = LogSinkStatus.FAILURE
                bullets.append("Test run completed with reported failures or errors.")
                suggested_action = "Review isolated failure logs."
            else:
                status = LogSinkStatus.SUCCESS
                bullets.append("Test run completed successfully with no fatal errors.")
                suggested_action = None

        delivered_text = "\n".join(bullets)
        return LogSinkConclusionCard(
            task_id=task.task_id,
            task_type=task.task_type,
            status=status,
            total_items=total,
            passed_items=passed,
            failed_items=failed,
            error_locations=error_locs[:5],
            bullet_points=bullets,
            suggested_action=suggested_action,
            raw_character_count=len(output),
            delivered_character_count=len(delivered_text),
        )

    def _distill_log_analysis(self, task: LogSinkTaskSpec, output: str) -> LogSinkConclusionCard:
        """Scan multi-megabyte server/runtime logs and extract recurring stack traces."""
        error_lines = self._LOG_ERROR_PATTERN.findall(output)
        bullets: list[str] = []
        locs: list[str] = []
        status = LogSinkStatus.SUCCESS if not error_lines else LogSinkStatus.FAILURE

        if error_lines:
            bullets.append(f"Detected {len(error_lines)} error/exception lines across log stream.")
            # Deduplicate and extract top errors
            seen: set[str] = set()
            for line in error_lines:
                clean_l = line.strip()[:100]
                if clean_l and clean_l not in seen:
                    seen.add(clean_l)
                    locs.append(clean_l)
                    if len(locs) >= 3:
                        break
            bullets.append(f"Top signature: {locs[0]}")
            suggested_action = f"Investigate root cause around: {locs[0][:60]}"
        else:
            bullets.append("Log inspection complete: no fatal exceptions or errors detected.")
            suggested_action = None

        delivered_text = "\n".join(bullets)
        return LogSinkConclusionCard(
            task_id=task.task_id,
            task_type=task.task_type,
            status=status,
            total_items=len(error_lines),
            passed_items=0,
            failed_items=len(error_lines),
            error_locations=locs,
            bullet_points=bullets,
            suggested_action=suggested_action,
            raw_character_count=len(output),
            delivered_character_count=len(delivered_text),
        )

    def _distill_git_history(self, task: LogSinkTaskSpec, output: str) -> LogSinkConclusionCard:
        """Condense expansive commit histories into high-level milestones."""
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        total_commits = len(lines)
        bullets = [
            f"Retrieved {total_commits} commits across target branch.",
            f"Head commit: {lines[0] if lines else 'None'}",
        ]
        if len(lines) > 1:
            bullets.append(f"Tail commit in window: {lines[-1]}")

        delivered_text = "\n".join(bullets)
        return LogSinkConclusionCard(
            task_id=task.task_id,
            task_type=task.task_type,
            status=LogSinkStatus.SUCCESS,
            total_items=total_commits,
            passed_items=total_commits,
            failed_items=0,
            bullet_points=bullets,
            raw_character_count=len(output),
            delivered_character_count=len(delivered_text),
        )

    def _distill_build_inspection(self, task: LogSinkTaskSpec, output: str) -> LogSinkConclusionCard:
        """Condense long build logs into compilation errors and warnings."""
        error_matches = [l for l in output.splitlines() if "error:" in l.lower() or "failed" in l.lower()]
        status = LogSinkStatus.FAILURE if error_matches else LogSinkStatus.SUCCESS
        bullets: list[str] = []
        locs: list[str] = []

        if error_matches:
            bullets.append(f"Build failed with {len(error_matches)} compilation errors.")
            for em in error_matches[:3]:
                locs.append(em.strip()[:100])
            bullets.append(f"First fatal error: {locs[0]}")
            suggested_action = "Fix syntax or type error indicated in compilation trace."
        else:
            bullets.append("Build completed cleanly with 0 compiler errors.")
            suggested_action = None

        delivered_text = "\n".join(bullets)
        return LogSinkConclusionCard(
            task_id=task.task_id,
            task_type=task.task_type,
            status=status,
            total_items=len(error_matches),
            failed_items=len(error_matches),
            error_locations=locs,
            bullet_points=bullets,
            suggested_action=suggested_action,
            raw_character_count=len(output),
            delivered_character_count=len(delivered_text),
        )

    def _distill_generic(self, task: LogSinkTaskSpec, output: str) -> LogSinkConclusionCard:
        """Generic summarizer for unclassified high-noise operations."""
        lines = [l for l in output.splitlines() if l.strip()]
        bullets = [
            f"Completed task with {len(lines)} lines of output suppressed in subagent sandbox.",
        ]
        if lines:
            bullets.append(f"Final output: {lines[-1][:120]}")

        delivered_text = "\n".join(bullets)
        return LogSinkConclusionCard(
            task_id=task.task_id,
            task_type=task.task_type,
            status=LogSinkStatus.SUCCESS,
            total_items=len(lines),
            bullet_points=bullets,
            raw_character_count=len(output),
            delivered_character_count=len(delivered_text),
        )
