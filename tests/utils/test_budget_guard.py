"""Tests for DailyBudgetGuard and BudgetChecker protocol."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from myrm_agent_harness.utils.token_economics.budget_guard import (
    BudgetChecker,
    BudgetStatus,
    DailyBudgetGuard,
)


class TestBudgetStatus:
    def test_enum_values(self) -> None:
        assert BudgetStatus.OK == "ok"
        assert BudgetStatus.WARNING == "warning"
        assert BudgetStatus.EXCEEDED == "exceeded"


class TestBudgetCheckerProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0)
        assert isinstance(guard, BudgetChecker)


class TestDailyBudgetGuard:
    def test_initial_state_ok(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0)
        assert guard.check_budget() == BudgetStatus.OK
        assert guard.today_cost == 0.0
        assert guard.daily_budget_usd == 10.0
        assert guard.get_remaining_budget() == 10.0

    def test_check_budget_ok(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0, warning_threshold=0.8)
        assert guard.check_budget(5.0) == BudgetStatus.OK

    def test_check_budget_warning(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0, warning_threshold=0.8)
        assert guard.check_budget(8.5) == BudgetStatus.WARNING

    def test_check_budget_exceeded(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0, warning_threshold=0.8)
        assert guard.check_budget(10.0) == BudgetStatus.EXCEEDED
        assert guard.check_budget(15.0) == BudgetStatus.EXCEEDED

    def test_record_cost_ok(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0)
        status = guard.record_cost(2.0)
        assert status == BudgetStatus.OK
        assert guard.today_cost == 2.0
        assert guard.get_remaining_budget() == 8.0

    def test_record_cost_warning(self) -> None:
        warned = []
        guard = DailyBudgetGuard(
            daily_budget_usd=10.0,
            warning_threshold=0.8,
            on_warning=lambda cost, budget: warned.append((cost, budget)),
        )
        guard.record_cost(8.5)
        assert guard.check_budget() == BudgetStatus.WARNING
        assert len(warned) == 1
        assert warned[0] == (8.5, 10.0)

    def test_record_cost_exceeded(self) -> None:
        exceeded = []
        guard = DailyBudgetGuard(
            daily_budget_usd=10.0,
            on_exceeded=lambda cost, budget: exceeded.append((cost, budget)),
        )
        status = guard.record_cost(12.0)
        assert status == BudgetStatus.EXCEEDED
        assert len(exceeded) == 1
        assert exceeded[0] == (12.0, 10.0)

    def test_cumulative_recording(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0, warning_threshold=0.8)
        assert guard.record_cost(3.0) == BudgetStatus.OK
        assert guard.record_cost(3.0) == BudgetStatus.OK
        assert guard.record_cost(3.0) == BudgetStatus.WARNING
        assert guard.today_cost == pytest.approx(9.0)
        assert guard.get_remaining_budget() == pytest.approx(1.0)

    def test_day_reset(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0)
        guard.record_cost(5.0)
        assert guard.today_cost == 5.0

        tomorrow = date(2099, 1, 2)
        with patch("myrm_agent_harness.utils.token_economics.budget_guard.date") as mock_date:
            mock_date.today.return_value = tomorrow
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            status = guard.check_budget()
            assert status == BudgetStatus.OK
            assert guard.today_cost == 0.0

    def test_remaining_budget_never_negative(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=5.0)
        guard.record_cost(10.0)
        assert guard.get_remaining_budget() == 0.0

    def test_no_callbacks_when_not_set(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=1.0)
        guard.record_cost(0.9)
        guard.record_cost(0.2)

    def test_warning_then_exceeded(self) -> None:
        warned = []
        exceeded = []
        guard = DailyBudgetGuard(
            daily_budget_usd=10.0,
            warning_threshold=0.8,
            on_warning=lambda c, b: warned.append(c),
            on_exceeded=lambda c, b: exceeded.append(c),
        )
        guard.record_cost(8.5)
        assert len(warned) == 1
        guard.record_cost(2.0)
        assert len(exceeded) == 1

    def test_initial_cost(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0, initial_cost=6.0)
        assert guard.today_cost == 6.0
        assert guard.get_remaining_budget() == pytest.approx(4.0)
        assert guard.check_budget() == BudgetStatus.OK

    def test_initial_cost_already_warning(self) -> None:
        guard = DailyBudgetGuard(
            daily_budget_usd=10.0, warning_threshold=0.8, initial_cost=8.5
        )
        assert guard.check_budget() == BudgetStatus.WARNING

    def test_initial_cost_already_exceeded(self) -> None:
        guard = DailyBudgetGuard(daily_budget_usd=10.0, initial_cost=12.0)
        assert guard.check_budget() == BudgetStatus.EXCEEDED
        assert guard.get_remaining_budget() == 0.0

    def test_initial_cost_plus_record(self) -> None:
        guard = DailyBudgetGuard(
            daily_budget_usd=10.0, warning_threshold=0.8, initial_cost=7.0
        )
        assert guard.record_cost(1.5) == BudgetStatus.WARNING
        assert guard.today_cost == pytest.approx(8.5)
