"""Tests for MultidimensionalBudgetGuard."""

from __future__ import annotations

import threading
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.utils.token_economics.budget_guard import BudgetChecker, BudgetStatus
from myrm_agent_harness.utils.token_economics.multidim_budget import (
    BudgetDimension,
    MultidimensionalBudgetGuard,
)


class TestBudgetDimension:
    def test_frozen_dataclass(self) -> None:
        dim = BudgetDimension(limit_usd=5.0)
        assert dim.limit_usd == 5.0
        assert dim.warning_threshold == 0.8
        with pytest.raises(Exception):
            dim.limit_usd = 10.0  # type: ignore[misc]


class TestMultidimensionalBudgetGuard:
    def test_implements_budget_checker_protocol(self) -> None:
        guard = MultidimensionalBudgetGuard(daily=BudgetDimension(limit_usd=10.0))
        assert isinstance(guard, BudgetChecker)

    def test_ok_status_when_within_limits(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=5.0),
            daily=BudgetDimension(limit_usd=10.0),
        )
        assert guard.check_budget(0.0) == BudgetStatus.OK
        assert guard.record_cost(1.0) == BudgetStatus.OK

    def test_session_warning(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=10.0, warning_threshold=0.8),
        )
        guard.record_cost(7.5)
        assert guard.check_budget(0.0) == BudgetStatus.OK
        status = guard.record_cost(0.6)
        assert status == BudgetStatus.WARNING

    def test_session_finalization(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=10.0),
            finalization_reserve_pct=0.15,
        )
        guard.record_cost(8.0)
        status = guard.record_cost(0.6)
        assert status == BudgetStatus.FINALIZATION

    def test_session_exceeded(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=5.0),
        )
        guard.record_cost(4.5)
        status = guard.record_cost(0.6)
        assert status == BudgetStatus.EXCEEDED

    def test_daily_warning(self) -> None:
        guard = MultidimensionalBudgetGuard(
            daily=BudgetDimension(limit_usd=10.0, warning_threshold=0.8),
        )
        status = guard.record_cost(8.1)
        assert status == BudgetStatus.WARNING

    def test_daily_finalization(self) -> None:
        guard = MultidimensionalBudgetGuard(
            daily=BudgetDimension(limit_usd=10.0),
            finalization_reserve_pct=0.15,
        )
        guard.record_cost(8.0)
        status = guard.record_cost(0.6)
        assert status == BudgetStatus.FINALIZATION

    def test_per_call_exceeded(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_call=BudgetDimension(limit_usd=1.0),
        )
        status = guard.check_budget(1.5)
        assert status == BudgetStatus.EXCEEDED

    def test_per_call_warning(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_call=BudgetDimension(limit_usd=1.0, warning_threshold=0.8),
        )
        status = guard.check_budget(0.85)
        assert status == BudgetStatus.WARNING

    def test_reset_session(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=5.0),
            daily=BudgetDimension(limit_usd=20.0),
        )
        guard.record_cost(4.5)
        assert guard.session_cost == 4.5
        assert guard.daily_cost == 4.5

        guard.reset_session()
        assert guard.session_cost == 0.0
        assert guard.daily_cost == 4.5

    def test_initial_daily_cost(self) -> None:
        guard = MultidimensionalBudgetGuard(
            daily=BudgetDimension(limit_usd=10.0, warning_threshold=0.8),
            initial_daily_cost=7.0,
        )
        assert guard.daily_cost == 7.0
        status = guard.record_cost(1.1)
        assert status == BudgetStatus.WARNING

    def test_get_remaining_budget(self) -> None:
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=5.0),
            daily=BudgetDimension(limit_usd=20.0),
        )
        guard.record_cost(3.0)
        remaining = guard.get_remaining_budget()
        assert remaining == pytest.approx(2.0, rel=1e-6)

    def test_remaining_with_no_dimensions(self) -> None:
        guard = MultidimensionalBudgetGuard()
        assert guard.get_remaining_budget() is None

    def test_strictest_status_wins(self) -> None:
        """If session is EXCEEDED but daily is WARNING, EXCEEDED should be returned."""
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=5.0),
            daily=BudgetDimension(limit_usd=100.0, warning_threshold=0.01),
        )
        guard.record_cost(5.5)
        status = guard.check_budget(0.0)
        assert status == BudgetStatus.EXCEEDED

    def test_callbacks_fire_once_per_session(self) -> None:
        on_warning = MagicMock()
        on_finalization = MagicMock()
        on_exceeded = MagicMock()

        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=10.0, warning_threshold=0.5),
            finalization_reserve_pct=0.15,
            on_warning=on_warning,
            on_finalization=on_finalization,
            on_exceeded=on_exceeded,
        )

        guard.record_cost(5.5)
        assert on_warning.call_count == 1

        guard.record_cost(0.5)
        assert on_warning.call_count == 1

        guard.record_cost(3.0)
        assert on_finalization.call_count == 1

        guard.record_cost(2.0)
        assert on_exceeded.call_count >= 1

    def test_day_reset_clears_daily_cost(self) -> None:
        guard = MultidimensionalBudgetGuard(
            daily=BudgetDimension(limit_usd=10.0),
            initial_daily_cost=8.0,
        )
        tomorrow = date(2099, 1, 1)
        with patch("myrm_agent_harness.utils.token_economics.multidim_budget.date") as mock_date:
            mock_date.today.return_value = tomorrow
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            status = guard.check_budget(0.0)
            assert status == BudgetStatus.OK
            assert guard.daily_cost == 0.0

    def test_thread_safety(self) -> None:
        """Concurrent record_cost from multiple threads should not corrupt state."""
        guard = MultidimensionalBudgetGuard(
            per_session=BudgetDimension(limit_usd=1000.0),
            daily=BudgetDimension(limit_usd=1000.0),
        )
        num_threads = 10
        calls_per_thread = 100
        cost_each = 0.01

        def worker() -> None:
            for _ in range(calls_per_thread):
                guard.record_cost(cost_each)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * calls_per_thread * cost_each
        assert guard.session_cost == pytest.approx(expected, rel=1e-6)
        assert guard.daily_cost == pytest.approx(expected, rel=1e-6)

    def test_properties_without_dimensions(self) -> None:
        guard = MultidimensionalBudgetGuard()
        assert guard.per_session_limit is None
        assert guard.daily_limit is None
        assert guard.session_cost == 0.0
        assert guard.daily_cost == 0.0

    def test_per_call_exceeded_triggers_correct_dimension(self) -> None:
        on_exceeded = MagicMock()
        guard = MultidimensionalBudgetGuard(
            per_call=BudgetDimension(limit_usd=1.0),
            per_session=BudgetDimension(limit_usd=100.0),
            on_exceeded=on_exceeded,
        )
        guard.record_cost(1.5)
        assert on_exceeded.call_count == 1
        args = on_exceeded.call_args[0]
        assert args[2] == "per_call"

    def test_daily_exceeded_dimension(self) -> None:
        on_exceeded = MagicMock()
        guard = MultidimensionalBudgetGuard(
            daily=BudgetDimension(limit_usd=5.0),
            on_exceeded=on_exceeded,
        )
        guard.record_cost(5.5)
        assert on_exceeded.call_count == 1
        args = on_exceeded.call_args[0]
        assert args[2] == "daily"

    def test_per_call_warning_dimension(self) -> None:
        """per_call warning only fires when session/daily aren't in warning range."""
        on_warning = MagicMock()
        guard = MultidimensionalBudgetGuard(
            per_call=BudgetDimension(limit_usd=1.0, warning_threshold=0.8),
            on_warning=on_warning,
        )
        guard.record_cost(0.85)
        assert on_warning.call_count == 1
        args = on_warning.call_args[0]
        assert args[2] == "per_call"

    def test_evaluate_status_finalization_daily_only(self) -> None:
        """Daily finalization when no per_session is configured."""
        guard = MultidimensionalBudgetGuard(
            daily=BudgetDimension(limit_usd=10.0),
            finalization_reserve_pct=0.15,
        )
        guard.record_cost(8.6)
        assert guard.check_budget(0.0) == BudgetStatus.FINALIZATION
