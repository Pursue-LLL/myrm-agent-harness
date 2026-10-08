# [INPUT] FetchBudgetStatus, TwoStageSearchConfig
# [OUTPUT] FetchBudgetGovernor
# [POS] Concurrency and depth governor preventing runaway crawling and enforcing interim synthesis

"""Fetch budget governor bounding concurrency and enforcing interim synthesis."""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.two_stage_search_extract.search_extract_types import (
    FetchBudgetExceededError,
    FetchBudgetStatus,
    TwoStageSearchConfig,
)


class FetchBudgetGovernor:
    """Governs per-session deep fetch budgets and triggers interim synthesis gates."""

    def __init__(self, config: TwoStageSearchConfig | None = None) -> None:
        self._config = config or TwoStageSearchConfig()
        # session_id -> (accumulated_fetches, consecutive_fetch_turns)
        self._session_records: dict[str, list[int]] = {}

    def get_status(self, session_id: str) -> FetchBudgetStatus:
        """Query current budget consumption status for a session."""
        record = self._session_records.get(session_id, [0, 0])
        accumulated = record[0]
        consecutive_turns = record[1]

        requires_synthesis = consecutive_turns >= self._config.interim_synthesis_threshold
        budget_exceeded = accumulated >= self._config.max_accumulated_fetches_per_session

        return FetchBudgetStatus(
            session_id=session_id,
            current_turn_fetches=0,
            max_fetches_per_turn=self._config.max_concurrent_fetches_per_turn,
            accumulated_fetches=accumulated,
            max_accumulated_fetches=self._config.max_accumulated_fetches_per_session,
            budget_exceeded=budget_exceeded,
            requires_interim_synthesis=requires_synthesis,
        )

    def check_and_authorize_fetches(
        self,
        session_id: str,
        requested_count: int,
    ) -> FetchBudgetStatus:
        """Authorize requested URL fetch batch or raise FetchBudgetExceededError."""
        if requested_count > self._config.max_concurrent_fetches_per_turn:
            raise FetchBudgetExceededError(
                f"Requested {requested_count} URLs exceeds max concurrent per-turn limit of "
                f"{self._config.max_concurrent_fetches_per_turn} URLs"
            )

        status = self.get_status(session_id)
        if status.budget_exceeded:
            raise FetchBudgetExceededError(
                f"Session '{session_id}' has exhausted total fetch budget "
                f"({status.accumulated_fetches}/{status.max_accumulated_fetches})"
            )

        if status.accumulated_fetches + requested_count > self._config.max_accumulated_fetches_per_session:
            raise FetchBudgetExceededError(
                f"Adding {requested_count} fetches would exceed session ceiling of "
                f"{self._config.max_accumulated_fetches_per_session}"
            )

        return status

    def commit_turn_fetches(
        self,
        session_id: str,
        performed_count: int,
    ) -> FetchBudgetStatus:
        """Record completed fetches for the current turn and update consecutive tracking."""
        record = self._session_records.setdefault(session_id, [0, 0])
        record[0] += performed_count
        if performed_count > 0:
            record[1] += 1
        else:
            record[1] = 0

        accumulated = record[0]
        consecutive_turns = record[1]

        requires_synthesis = consecutive_turns >= self._config.interim_synthesis_threshold
        budget_exceeded = accumulated >= self._config.max_accumulated_fetches_per_session

        return FetchBudgetStatus(
            session_id=session_id,
            current_turn_fetches=performed_count,
            max_fetches_per_turn=self._config.max_concurrent_fetches_per_turn,
            accumulated_fetches=accumulated,
            max_accumulated_fetches=self._config.max_accumulated_fetches_per_session,
            budget_exceeded=budget_exceeded,
            requires_interim_synthesis=requires_synthesis,
        )

    def reset_consecutive_turns(self, session_id: str) -> None:
        """Reset consecutive fetch count once model outputs an interim synthesis."""
        if session_id in self._session_records:
            self._session_records[session_id][1] = 0

    def reset_session(self, session_id: str) -> None:
        """Completely reset tracking for a given session."""
        self._session_records.pop(session_id, None)
