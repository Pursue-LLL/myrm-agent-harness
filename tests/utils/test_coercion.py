"""Tests for utils.coercion - parse_float, parse_int, parse_timeout."""

import pytest

from myrm_agent_harness.utils.coercion import parse_float, parse_int, parse_timeout

# =========================================================================
# parse_float
# =========================================================================


class TestParseFloat:
    def test_normal_int(self) -> None:
        assert parse_float(42, 0.0) == 42.0

    def test_normal_float(self) -> None:
        assert parse_float(3.14, 0.0) == pytest.approx(3.14)

    def test_string_number(self) -> None:
        assert parse_float("2.5", 0.0) == pytest.approx(2.5)

    def test_string_int(self) -> None:
        assert parse_float("10", 0.0) == pytest.approx(10.0)

    def test_none_returns_default(self) -> None:
        assert parse_float(None, 99.0) == 99.0

    def test_bool_returns_default(self) -> None:
        assert parse_float(True, 99.0) == 99.0
        assert parse_float(False, 99.0) == 99.0

    def test_nan_returns_default(self) -> None:
        assert parse_float(float("nan"), 99.0) == 99.0

    def test_inf_returns_default(self) -> None:
        assert parse_float(float("inf"), 99.0) == 99.0

    def test_neg_inf_returns_default(self) -> None:
        assert parse_float(float("-inf"), 99.0) == 99.0

    def test_negative_value(self) -> None:
        assert parse_float(-5.0, 0.0) == -5.0

    def test_negative_clamped_by_min(self) -> None:
        assert parse_float(-5.0, 0.0, min_val=0.0) == 0.0

    def test_value_clamped_by_max(self) -> None:
        assert parse_float(999.0, 0.0, max_val=100.0) == 100.0

    def test_value_within_bounds(self) -> None:
        assert parse_float(50.0, 0.0, min_val=0.0, max_val=100.0) == 50.0

    def test_string_nan_returns_default(self) -> None:
        assert parse_float("nan", 99.0) == 99.0

    def test_string_inf_returns_default(self) -> None:
        assert parse_float("inf", 99.0) == 99.0

    def test_non_numeric_string_returns_default(self) -> None:
        assert parse_float("abc", 99.0) == 99.0

    def test_empty_string_returns_default(self) -> None:
        assert parse_float("", 99.0) == 99.0

    def test_list_returns_default(self) -> None:
        assert parse_float([1, 2], 99.0) == 99.0

    def test_dict_returns_default(self) -> None:
        assert parse_float({"a": 1}, 99.0) == 99.0


# =========================================================================
# parse_int
# =========================================================================


class TestParseInt:
    def test_normal_int(self) -> None:
        assert parse_int(42, 0) == 42

    def test_normal_float(self) -> None:
        assert parse_int(3.7, 0) == 3

    def test_string_int(self) -> None:
        assert parse_int("10", 0) == 10

    def test_string_float(self) -> None:
        assert parse_int("3.7", 0) == 3

    def test_none_returns_default(self) -> None:
        assert parse_int(None, 99) == 99

    def test_bool_returns_default(self) -> None:
        assert parse_int(True, 99) == 99
        assert parse_int(False, 99) == 99

    def test_nan_returns_default(self) -> None:
        assert parse_int(float("nan"), 99) == 99

    def test_inf_returns_default(self) -> None:
        assert parse_int(float("inf"), 99) == 99

    def test_neg_inf_returns_default(self) -> None:
        assert parse_int(float("-inf"), 99) == 99

    def test_negative_value(self) -> None:
        assert parse_int(-5, 0) == -5

    def test_negative_clamped_by_min(self) -> None:
        assert parse_int(-5, 0, min_val=0) == 0

    def test_value_clamped_by_max(self) -> None:
        assert parse_int(999, 0, max_val=100) == 100

    def test_value_within_bounds(self) -> None:
        assert parse_int(50, 0, min_val=0, max_val=100) == 50

    def test_non_numeric_string_returns_default(self) -> None:
        assert parse_int("abc", 99) == 99

    def test_empty_string_returns_default(self) -> None:
        assert parse_int("", 99) == 99

    def test_list_returns_default(self) -> None:
        assert parse_int([1, 2], 99) == 99

    def test_string_nan_returns_default(self) -> None:
        assert parse_int("nan", 99) == 99

    def test_string_inf_returns_default(self) -> None:
        assert parse_int("inf", 99) == 99


# =========================================================================
# parse_timeout
# =========================================================================


class TestParseTimeout:
    def test_normal_value(self) -> None:
        assert parse_timeout(60.0) == 60.0

    def test_default(self) -> None:
        assert parse_timeout(None) == 120.0

    def test_below_min_clamped(self) -> None:
        assert parse_timeout(0.01) == 0.1

    def test_above_max_clamped(self) -> None:
        assert parse_timeout(9999.0) == 3600.0

    def test_nan_returns_default(self) -> None:
        assert parse_timeout(float("nan")) == 120.0

    def test_inf_returns_default(self) -> None:
        assert parse_timeout(float("inf")) == 120.0

    def test_negative_returns_min(self) -> None:
        assert parse_timeout(-10.0) == 0.1

    def test_string_value(self) -> None:
        assert parse_timeout("30") == 30.0

    def test_custom_default(self) -> None:
        assert parse_timeout(None, default=60.0) == 60.0

    def test_custom_bounds(self) -> None:
        assert parse_timeout(5.0, min_val=1.0, max_val=10.0) == 5.0
        assert parse_timeout(0.5, min_val=1.0, max_val=10.0) == 1.0
        assert parse_timeout(20.0, min_val=1.0, max_val=10.0) == 10.0
