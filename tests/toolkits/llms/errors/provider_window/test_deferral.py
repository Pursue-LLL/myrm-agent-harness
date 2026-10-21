import pytest

from myrm_agent_harness.toolkits.llms.errors import FailoverReason, MyrmLLMError
from myrm_agent_harness.toolkits.llms.errors.provider_window import HOLD_MAX_S, deferral_wait_s


def _error(context: dict[str, object] | None) -> MyrmLLMError:
    return MyrmLLMError(error_code=FailoverReason.RATE_LIMIT, default_msg="limit", context=context)


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ({"cooldown_remaining_ms": 90_000}, 90.0),
        ({"cooldown_remaining_ms": int(HOLD_MAX_S * 1000)}, HOLD_MAX_S),
        ({"cooldown_remaining_ms": int(HOLD_MAX_S * 1000) + 1}, None),
        ({"cooldown_remaining_ms": 0}, None),
        ({"cooldown_remaining_ms": -5}, None),
        ({"cooldown_remaining_ms": True}, None),
        ({"cooldown_remaining_ms": "90000"}, None),
        ({"cooldown_remaining_ms": None}, None),
        ({}, None),
        (None, None),
    ],
)
def test_waitable_boundary_only(context, expected):
    assert deferral_wait_s(_error(context)) == expected


def test_foreign_exceptions_carry_no_boundary():
    assert deferral_wait_s(RuntimeError("429 retry after 30 seconds")) is None
