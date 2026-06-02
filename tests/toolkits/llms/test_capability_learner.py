"""Tests for ModelCapabilityLearner — in-process model capability cache."""

from __future__ import annotations

import time
from unittest.mock import patch

from myrm_agent_harness.toolkits.llms.capability_learner import (
    ModelCapabilityLearner,
    get_capability_learner,
)


class TestModelCapabilityLearner:
    """Core learn/get/clear functionality."""

    def setup_method(self) -> None:
        ModelCapabilityLearner._instance = None
        self.learner = get_capability_learner()

    def teardown_method(self) -> None:
        ModelCapabilityLearner._instance = None

    def test_singleton(self) -> None:
        a = get_capability_learner()
        b = get_capability_learner()
        assert a is b

    def test_learn_and_get(self) -> None:
        self.learner.learn("gpt-4o", "rejects_media", True)
        assert self.learner.get("gpt-4o", "rejects_media") is True

    def test_get_default_when_not_learned(self) -> None:
        assert self.learner.get("gpt-4o", "unknown_cap") is None
        assert self.learner.get("gpt-4o", "unknown_cap", False) is False

    def test_overwrite(self) -> None:
        self.learner.learn("gpt-4o", "rejects_media", True)
        self.learner.learn("gpt-4o", "rejects_media", False)
        assert self.learner.get("gpt-4o", "rejects_media") is False

    def test_different_models(self) -> None:
        self.learner.learn("gpt-4o", "rejects_media", True)
        self.learner.learn("claude-3", "rejects_media", False)
        assert self.learner.get("gpt-4o", "rejects_media") is True
        assert self.learner.get("claude-3", "rejects_media") is False

    def test_different_capabilities(self) -> None:
        self.learner.learn("gpt-4o", "rejects_media", True)
        self.learner.learn("gpt-4o", "supports_tools", True)
        assert self.learner.get("gpt-4o", "rejects_media") is True
        assert self.learner.get("gpt-4o", "supports_tools") is True

    def test_clear(self) -> None:
        self.learner.learn("gpt-4o", "rejects_media", True)
        assert self.learner.size() == 1
        self.learner.clear()
        assert self.learner.size() == 0
        assert self.learner.get("gpt-4o", "rejects_media") is None

    def test_size(self) -> None:
        assert self.learner.size() == 0
        self.learner.learn("a", "cap1", True)
        self.learner.learn("b", "cap2", False)
        assert self.learner.size() == 2

    def test_ttl_expiration(self) -> None:
        self.learner.learn("gpt-4o", "rejects_media", True, ttl_seconds=1)
        assert self.learner.get("gpt-4o", "rejects_media") is True
        with patch(
            "myrm_agent_harness.toolkits.llms.capability_learner.time"
        ) as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 2
            assert self.learner.get("gpt-4o", "rejects_media") is None

    def test_custom_ttl(self) -> None:
        self.learner.learn("gpt-4o", "rejects_media", True, ttl_seconds=7200)
        assert self.learner.get("gpt-4o", "rejects_media") is True

    def test_thread_safety(self) -> None:
        import threading

        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i in range(100):
                    self.learner.learn(f"model-{i}", "cap", True)
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for i in range(100):
                    self.learner.get(f"model-{i}", "cap")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
