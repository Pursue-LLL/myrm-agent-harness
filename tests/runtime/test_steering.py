"""Tests for SteeringToken and steering ContextVar utilities."""

import threading

from myrm_agent_harness.utils.runtime.steering import (
    SteeringToken,
    get_steering_token,
    set_steering_token,
)


class TestSteeringToken:
    """SteeringToken unit tests covering queue, activation, reset, and thread safety."""

    def test_initial_state(self) -> None:
        token = SteeringToken()
        assert not token.has_pending
        assert not token.is_active
        assert not token.steering_applied

    def test_steer_queues_message(self) -> None:
        token = SteeringToken()
        token.steer("go left")
        assert token.has_pending

    def test_activate_returns_messages_and_sets_active(self) -> None:
        token = SteeringToken()
        token.steer("msg1")
        token.steer("msg2")

        msgs = token.activate()
        assert msgs == ["msg1", "msg2"]
        assert token.is_active
        assert token.steering_applied
        assert not token.has_pending

    def test_activate_idempotent_when_already_active(self) -> None:
        token = SteeringToken()
        token.steer("a")
        token.activate()
        assert token.activate() == []

    def test_activate_empty_when_no_pending(self) -> None:
        token = SteeringToken()
        assert token.activate() == []
        assert not token.is_active

    def test_collect_all_merges_activated_and_queued(self) -> None:
        token = SteeringToken()
        token.steer("early")
        token.activate()
        token.steer("late")

        all_msgs = token.collect_all_steering_messages()
        assert all_msgs == ["early", "late"]
        assert not token.has_pending

    def test_collect_all_empty_after_drain(self) -> None:
        token = SteeringToken()
        token.steer("x")
        token.activate()
        token.collect_all_steering_messages()
        assert token.collect_all_steering_messages() == []

    def test_reset_turn_preserves_queue(self) -> None:
        token = SteeringToken()
        token.steer("before_activate")
        token.activate()
        token.steer("after_activate")
        token.reset_turn()

        assert not token.is_active
        assert not token.steering_applied
        assert token.has_pending

    def test_thread_safety_concurrent_steer(self) -> None:
        token = SteeringToken()
        barrier = threading.Barrier(10)

        def steer_worker(i: int) -> None:
            barrier.wait()
            token.steer(f"msg-{i}")

        threads = [threading.Thread(target=steer_worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        msgs = token.activate()
        assert len(msgs) == 10
        assert set(msgs) == {f"msg-{i}" for i in range(10)}


    def test_reset_turn_then_steer_and_activate_again(self) -> None:
        """After reset_turn, new steer+activate cycle works correctly."""
        token = SteeringToken()
        token.steer("round1")
        token.activate()
        token.reset_turn()

        token.steer("round2")
        msgs = token.activate()
        assert msgs == ["round2"]
        assert token.is_active
        assert token.steering_applied

    def test_concurrent_activate_only_one_wins(self) -> None:
        """Only one activate() call returns messages when racing."""
        token = SteeringToken()
        token.steer("race-msg")
        barrier = threading.Barrier(5)
        results: list[list[str]] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = token.activate()
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        non_empty = [r for r in results if r]
        assert len(non_empty) == 1
        assert non_empty[0] == ["race-msg"]

    def test_steer_empty_string_is_queued(self) -> None:
        """Empty string steer is queued (validation is API-level responsibility)."""
        token = SteeringToken()
        token.steer("")
        assert token.has_pending
        msgs = token.activate()
        assert msgs == [""]

    def test_steer_unicode_and_special_chars(self) -> None:
        """Unicode, emoji, newlines, and special chars pass through correctly."""
        token = SteeringToken()
        special = "请用中文回答\n <script>alert('xss')</script>"
        token.steer(special)
        msgs = token.activate()
        assert msgs == [special]

    def test_steer_very_long_message(self) -> None:
        """Token handles very long messages without truncation at this layer."""
        token = SteeringToken()
        long_msg = "x" * 100_000
        token.steer(long_msg)
        msgs = token.activate()
        assert msgs == [long_msg]

    def test_collect_all_after_reset_only_gets_queue(self) -> None:
        """After reset_turn, collect_all only returns queue items, not activated."""
        token = SteeringToken()
        token.steer("activated-msg")
        token.activate()
        token.reset_turn()
        token.steer("new-queue-msg")
        msgs = token.collect_all_steering_messages()
        assert msgs == ["new-queue-msg"]

    def test_multiple_reset_cycles(self) -> None:
        """Token works correctly across multiple reset cycles (simulating multi-turn)."""
        token = SteeringToken()
        for i in range(5):
            token.steer(f"turn-{i}")
            msgs = token.activate()
            assert msgs == [f"turn-{i}"]
            token.reset_turn()
            assert not token.is_active
            assert not token.steering_applied


class TestSteeringContextVar:
    """Tests for ContextVar-based request isolation."""

    def test_default_is_none(self) -> None:
        assert get_steering_token() is None

    def test_set_and_get(self) -> None:
        token = SteeringToken()
        set_steering_token(token)
        assert get_steering_token() is token
        set_steering_token(None)

    def test_isolation_across_threads(self) -> None:
        parent_token = SteeringToken()
        set_steering_token(parent_token)

        child_result: list[SteeringToken | None] = []

        def child() -> None:
            child_result.append(get_steering_token())

        t = threading.Thread(target=child)
        t.start()
        t.join()

        assert get_steering_token() is parent_token
        assert child_result[0] is None
        set_steering_token(None)

    def test_contextvar_overwrite(self) -> None:
        """Setting a new token replaces the old one."""
        t1 = SteeringToken()
        t2 = SteeringToken()
        set_steering_token(t1)
        set_steering_token(t2)
        assert get_steering_token() is t2
        set_steering_token(None)

    def test_contextvar_set_none_clears(self) -> None:
        """Setting None clears the token."""
        token = SteeringToken()
        set_steering_token(token)
        set_steering_token(None)
        assert get_steering_token() is None
