"""Tests for SkillAgent session-end privacy context re-establishment.

Validates that ``_cleanup_session`` rebuilds the security/policy/store/closure
context after ``cleanup_run`` cleared it, so end_session flush and
auto-extraction memories are persisted with the same PII protection as in-run
writes (regression: fire-and-forget writes ran with a cleared context).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy
from myrm_agent_harness.agent.skill_agent._privacy_context import (
    reestablish_privacy_context,
    teardown_privacy_context,
)
from myrm_agent_harness.agent.skill_agent.review import SkillAgentReviewMixin


def _fake_policy(enabled: bool = True) -> PrivacyPolicy:
    return PrivacyPolicy(
        enabled=enabled,
        s2_action=PIIAction.PSEUDONYMIZE,
        s3_action=PIIAction.REDACT,
        deep_scan=True,
    )


@dataclass
class _FakeSecurityConfig:
    privacy_policy: PrivacyPolicy | None = None


@dataclass
class _FakeConfig:
    security_config: _FakeSecurityConfig | None = None


class FakeAgent(SkillAgentReviewMixin):
    def __init__(
        self,
        *,
        config: Any = None,
        last_context: dict[str, object] | None = None,
    ) -> None:
        self.config = config or _FakeConfig()
        self._last_context = last_context


def _make_agent(enabled: bool = True) -> FakeAgent:
    config = _FakeConfig(security_config=_FakeSecurityConfig(privacy_policy=_fake_policy(enabled)))
    return FakeAgent(config=config, last_context={"workspace_path": "/tmp/ws"})


class TestReestablishPrivacyContext:
    def test_skips_when_context_alive(self) -> None:
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
            return_value=MagicMock(),
        ):
            restored = reestablish_privacy_context(_make_agent())
        assert restored.restored is False

    def test_skips_without_security_config(self) -> None:
        agent = FakeAgent()
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
            return_value=None,
        ):
            restored = reestablish_privacy_context(agent)
        assert restored.restored is False

    def test_skips_when_privacy_disabled(self) -> None:
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
            return_value=None,
        ):
            restored = reestablish_privacy_context(_make_agent(enabled=False))
        assert restored.restored is False

    def test_skips_without_workspace(self) -> None:
        agent = FakeAgent(
            config=_FakeConfig(security_config=_FakeSecurityConfig(privacy_policy=_fake_policy(True))),
            last_context={},
        )
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
            return_value=None,
        ):
            restored = reestablish_privacy_context(agent)
        assert restored.restored is False

    def test_reestablishes_and_tears_down_context(self) -> None:
        mock_store = MagicMock()
        with (
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.detection.pseudonym_store.get_pseudonym_store",
                return_value=mock_store,
            ),
        ):
            agent = _make_agent()
            restored = reestablish_privacy_context(agent)
            assert restored.restored is True

            from myrm_agent_harness.agent.middlewares._session_context import (
                get_privacy_policy,
                get_pseudonym_store,
            )
            from myrm_agent_harness.core.security.persistence.content_scan import (
                get_pii_pseudonymizer,
            )

            assert get_privacy_policy().enabled is True
            assert get_pseudonym_store() is mock_store
            assert get_pii_pseudonymizer() is not None

            teardown_privacy_context(restored)
            assert get_privacy_policy().enabled is False
            assert get_pseudonym_store() is None
            assert get_pii_pseudonymizer() is None

    def test_reestablishes_with_deep_scan_only_policy(self) -> None:
        """Deep scan alone (S2/S3=REDACT) must still initialize the store.

        Regression: needs_store only considered PSEUDONYMIZE actions, so
        privacyDeepScan + the default REDACT actions silently disabled the LLM
        deep scan on every memory-write path.
        """
        mock_store = MagicMock()
        policy = PrivacyPolicy(
            enabled=True,
            s2_action=PIIAction.REDACT,
            s3_action=PIIAction.REDACT,
            deep_scan=True,
        )
        agent = FakeAgent(
            config=_FakeConfig(security_config=_FakeSecurityConfig(privacy_policy=policy)),
            last_context={"workspace_path": "/tmp/ws"},
        )
        with (
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.detection.pseudonym_store.get_pseudonym_store",
                return_value=mock_store,
            ),
        ):
            restored = reestablish_privacy_context(agent)
        assert restored.restored is True

        from myrm_agent_harness.agent.middlewares._session_context import (
            get_pseudonym_store,
        )

        assert get_pseudonym_store() is mock_store
        teardown_privacy_context(restored)
        assert get_pseudonym_store() is None

    def test_teardown_is_noop_when_not_restored(self) -> None:
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
            return_value=None,
        ):
            agent = _make_agent(enabled=False)
            restored = reestablish_privacy_context(agent)
        assert restored.restored is False
        teardown_privacy_context(restored)  # must not raise

    def test_partial_failure_restores_all_contextvars(self) -> None:
        """A store-init exception must leave no partial context behind.

        Regression: only security config was restored on failure, so a store
        set before the closure registration raised would leak into the current
        task context (and teardown was skipped because restored=False).
        """
        mock_store = MagicMock()

        def _boom(*args: object, **kwargs: object) -> object:
            raise RuntimeError("store init exploded")

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.detection.pseudonym_store.get_pseudonym_store",
                return_value=mock_store,
            ),
            patch(
                "myrm_agent_harness.agent._internals.run_lifecycle._init_pseudonym_store",
                side_effect=_boom,
            ),
        ):
            restored = reestablish_privacy_context(_make_agent())
        assert restored.restored is False

        from myrm_agent_harness.agent.middlewares._session_context import (
            get_privacy_policy,
            get_pseudonym_store,
            get_security_config,
        )
        from myrm_agent_harness.core.security.persistence.content_scan import (
            get_pii_pseudonymizer,
        )

        assert get_security_config() is None
        assert get_pseudonym_store() is None
        assert get_pii_pseudonymizer() is None
        assert get_privacy_policy().enabled is False


class TestCleanupSessionPrivacy:
    @pytest.mark.asyncio
    async def test_auto_extract_task_inherits_rebuilt_context(self) -> None:
        """auto_extract_memories must see the rebuilt policy + closure.

        Regression: the fire-and-forget task used to run after run-end cleanup
        cleared the ContextVars, so extracted memories were persisted without
        PII protection even when the user enabled it.
        """
        import asyncio

        from myrm_agent_harness.core.security.persistence.content_scan import (
            get_pii_pseudonymizer,
        )

        mock_store = MagicMock()
        mm = MagicMock()
        mm.active_session = None
        mm.end_session = AsyncMock(return_value=[])
        mm.check_session_recurrence = AsyncMock()
        agent = _make_agent()
        agent.memory_manager = mm
        agent._enable_memory_auto_extraction = True
        agent.llm = MagicMock()

        observed: list[object | None] = []

        async def fake_auto_extract(
            query: object,
            chat_history: object,
            memory_manager: object,
            llm: object,
            **kwargs: object,
        ) -> None:
            await asyncio.sleep(0.01)
            observed.append(get_pii_pseudonymizer())
            observed.append(kwargs.get("deep_scan"))

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_security_config",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.detection.pseudonym_store.get_pseudonym_store",
                return_value=mock_store,
            ),
            patch(
                "myrm_agent_harness.agent._internals.memory_extraction.auto_extract_memories",
                side_effect=fake_auto_extract,
            ),
        ):
            await agent._cleanup_session("query", None, ["reply"])

        await asyncio.sleep(0.05)
        assert observed[0] is not None  # closure inherited by the task
        assert observed[1] is True  # deep_scan resolved from rebuilt policy
        # Context torn down after cleanup session
        assert get_pii_pseudonymizer() is None

    @pytest.mark.asyncio
    async def test_auto_extract_short_circuits_when_l3_extraction_disabled(self) -> None:
        """当 memory_policy.allow_l3_extraction=False 时，必须短路阻断后台 LLM 抽取任务。"""
        import asyncio
        from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy

        mm = MagicMock()
        mm.active_session = None
        mm.end_session = AsyncMock(return_value=[])
        mm.check_session_recurrence = AsyncMock()
        mm.policy = AgentMemoryPolicy.preset_l2_flow(task_id="t1")  # allow_l3_extraction=False
        agent = _make_agent()
        agent.memory_manager = mm
        agent._enable_memory_auto_extraction = True
        agent.llm = MagicMock()

        extract_called = False

        async def fake_auto_extract(*args: object, **kwargs: object) -> None:
            nonlocal extract_called
            extract_called = True

        with patch(
            "myrm_agent_harness.agent._internals.memory_extraction.auto_extract_memories",
            side_effect=fake_auto_extract,
        ):
            await agent._cleanup_session("query", None, ["reply"])

        await asyncio.sleep(0.05)
        assert extract_called is False

