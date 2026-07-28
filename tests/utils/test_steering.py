"""Tests for myrm_agent_harness.utils.runtime.steering."""

from myrm_agent_harness.utils.runtime.steering import (
    SteeringToken,
    get_steering_token,
    set_steering_token,
)


def test_steer_queues_messages() -> None:
    t = SteeringToken()
    t.steer("a")
    t.steer("b")
    assert t.has_pending is True


def test_has_pending_empty_queue() -> None:
    t = SteeringToken()
    assert t.has_pending is False


def test_is_active_and_steering_applied_before_activate() -> None:
    t = SteeringToken()
    assert t.is_active is False
    assert t.steering_applied is False


def test_activate_returns_messages_sets_flags() -> None:
    t = SteeringToken()
    t.steer("x")
    msgs = t.activate()
    assert msgs == ["x"]
    assert t.is_active is True
    assert t.steering_applied is True
    assert t.has_pending is False


def test_activate_second_call_returns_empty() -> None:
    t = SteeringToken()
    t.steer("one")
    assert t.activate() == ["one"]
    t.steer("late")
    assert t.activate() == []


def test_activate_empty_queue_returns_empty() -> None:
    t = SteeringToken()
    assert t.activate() == []


def test_collect_all_merges_activated_and_queue() -> None:
    t = SteeringToken()
    t.steer("first")
    assert t.activate() == ["first"]
    t.steer("second")
    assert t.collect_all_steering_messages() == ["first", "second"]


def test_reset_turn_clears_flags_keeps_queue() -> None:
    t = SteeringToken()
    t.steer("q1")
    t.activate()
    t.steer("q2")
    t.reset_turn()
    assert t.is_active is False
    assert t.steering_applied is False
    assert t.has_pending is True
    assert t.collect_all_steering_messages() == ["q2"]


def test_redirect_queues_and_sets_flag() -> None:
    t = SteeringToken()
    t.redirect("correction")
    assert t.has_pending is True
    assert t.redirect_requested is True


def test_redirect_requested_false_initially() -> None:
    t = SteeringToken()
    assert t.redirect_requested is False


def test_redirect_reset_by_reset_turn() -> None:
    t = SteeringToken()
    t.redirect("x")
    assert t.redirect_requested is True
    t.reset_turn()
    assert t.redirect_requested is False
    assert t.has_pending is True


def test_redirect_messages_collectible() -> None:
    t = SteeringToken()
    t.redirect("fix this")
    msgs = t.collect_all_steering_messages()
    assert msgs == ["fix this"]


def test_get_set_steering_token() -> None:
    prev = get_steering_token()
    token = SteeringToken()
    set_steering_token(token)
    assert get_steering_token() is token
    set_steering_token(prev)
