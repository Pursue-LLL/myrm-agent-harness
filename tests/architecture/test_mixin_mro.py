"""Architecture gate: aggregate-root mixin MRO order.

BrowserSession, ChatLiteLLM, OptimizationScheduler, SubagentExecutor, and BashExecutor
rely on multiple inheritance. Wrong mixin order silently changes which implementation
runs. These tests lock the intended MRO prefix and method resolution owners.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from myrm_agent_harness.agent.meta_tools.bash.bash_executor import BashExecutor
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_background_mixin import BashExecutorBackgroundMixin
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_context_mixin import BashExecutorContextMixin
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_execute_mixin import BashExecutorExecuteMixin
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_prepare_mixin import BashExecutorPrepareMixin
from myrm_agent_harness.agent.skills.optimization.scheduler import OptimizationScheduler
from myrm_agent_harness.agent.skills.optimization.scheduler_batch_mixin import (
    OptimizationSchedulerBatchMixin,
)
from myrm_agent_harness.agent.skills.optimization.scheduler_monitoring_mixin import (
    OptimizationSchedulerMonitoringMixin,
)
from myrm_agent_harness.agent.skills.optimization.scheduler_queue_mixin import (
    OptimizationSchedulerQueueMixin,
)
from myrm_agent_harness.agent.skills.optimization.scheduler_resilience_mixin import (
    OptimizationSchedulerResilienceMixin,
)
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.executor_attempt_mixin import SubagentExecutorAttemptMixin
from myrm_agent_harness.agent.sub_agents.executor_delegation_mixin import SubagentExecutorDelegationMixin
from myrm_agent_harness.agent.sub_agents.executor_retry_mixin import SubagentExecutorRetryMixin
from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.browser_session_extraction_mixin import (
    BrowserSessionExtractionMixin,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_lifecycle_mixin import (
    BrowserSessionLifecycleMixin,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    BrowserSessionNavigationMixin,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_network_mixin import (
    BrowserSessionNetworkMixin,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_page_mixin import (
    BrowserSessionPageMixin,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
    BrowserSessionPersistenceMixin,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_recording_mixin import (
    BrowserSessionRecordingMixin,
)
from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.chat_model_async_mixin import ChatLiteLLMAsyncMixin
from myrm_agent_harness.toolkits.llms.adapters.chat_model_message_mixin import ChatLiteLLMMessageMixin
from myrm_agent_harness.toolkits.llms.adapters.chat_model_sync_mixin import ChatLiteLLMSyncMixin

_EXPECTED_BROWSER_SESSION_MIXIN_MRO: tuple[type[object], ...] = (
    BrowserSession,
    BrowserSessionPersistenceMixin,
    BrowserSessionRecordingMixin,
    BrowserSessionExtractionMixin,
    BrowserSessionPageMixin,
    BrowserSessionNetworkMixin,
    BrowserSessionNavigationMixin,
    BrowserSessionLifecycleMixin,
    object,
)


@pytest.mark.architecture
def test_browser_session_mixin_mro_prefix() -> None:
    assert BrowserSession.__mro__[: len(_EXPECTED_BROWSER_SESSION_MIXIN_MRO)] == _EXPECTED_BROWSER_SESSION_MIXIN_MRO


@pytest.mark.architecture
def test_browser_session_navigate_resolves_to_navigation_mixin() -> None:
    owner = next(c for c in BrowserSession.__mro__ if "navigate" in c.__dict__)
    assert owner is BrowserSessionNavigationMixin


@pytest.mark.architecture
def test_browser_session_initialize_components_resolves_to_lifecycle_mixin() -> None:
    owner = next(c for c in BrowserSession.__mro__ if "_initialize_components" in c.__dict__)
    assert owner is BrowserSessionLifecycleMixin


@pytest.mark.architecture
def test_chat_lite_llm_mixin_order_before_base_chat_model() -> None:
    mro = ChatLiteLLM.__mro__
    message_idx = mro.index(ChatLiteLLMMessageMixin)
    sync_idx = mro.index(ChatLiteLLMSyncMixin)
    async_idx = mro.index(ChatLiteLLMAsyncMixin)
    base_idx = mro.index(BaseChatModel)
    assert message_idx < sync_idx < async_idx < base_idx


_EXPECTED_OPTIMIZATION_SCHEDULER_MIXIN_MRO: tuple[type[object], ...] = (
    OptimizationScheduler,
    OptimizationSchedulerMonitoringMixin,
    OptimizationSchedulerBatchMixin,
    OptimizationSchedulerQueueMixin,
    OptimizationSchedulerResilienceMixin,
    object,
)


@pytest.mark.architecture
def test_optimization_scheduler_mixin_mro_prefix() -> None:
    assert (
        OptimizationScheduler.__mro__[: len(_EXPECTED_OPTIMIZATION_SCHEDULER_MIXIN_MRO)]
        == _EXPECTED_OPTIMIZATION_SCHEDULER_MIXIN_MRO
    )


@pytest.mark.architecture
def test_optimization_scheduler_start_monitoring_resolves_to_monitoring_mixin() -> None:
    owner = next(c for c in OptimizationScheduler.__mro__ if "start_monitoring" in c.__dict__)
    assert owner is OptimizationSchedulerMonitoringMixin


_EXPECTED_SUBAGENT_EXECUTOR_MIXIN_MRO: tuple[type[object], ...] = (
    SubagentExecutor,
    SubagentExecutorRetryMixin,
    SubagentExecutorAttemptMixin,
    SubagentExecutorDelegationMixin,
    object,
)


@pytest.mark.architecture
def test_subagent_executor_mixin_mro_prefix() -> None:
    assert (
        SubagentExecutor.__mro__[: len(_EXPECTED_SUBAGENT_EXECUTOR_MIXIN_MRO)]
        == _EXPECTED_SUBAGENT_EXECUTOR_MIXIN_MRO
    )


@pytest.mark.architecture
def test_subagent_executor_run_with_retry_resolves_to_retry_mixin() -> None:
    owner = next(c for c in SubagentExecutor.__mro__ if "run_with_retry" in c.__dict__)
    assert owner is SubagentExecutorRetryMixin


@pytest.mark.architecture
def test_subagent_executor_attach_delegation_resolves_to_delegation_mixin() -> None:
    owner = next(c for c in SubagentExecutor.__mro__ if "_attach_child_delegation_tools" in c.__dict__)
    assert owner is SubagentExecutorDelegationMixin


@pytest.mark.architecture
def test_subagent_executor_run_single_attempt_resolves_to_attempt_mixin() -> None:
    owner = next(c for c in SubagentExecutor.__mro__ if "_run_single_attempt" in c.__dict__)
    assert owner is SubagentExecutorAttemptMixin


_EXPECTED_BASH_EXECUTOR_MIXIN_MRO: tuple[type[object], ...] = (
    BashExecutor,
    BashExecutorExecuteMixin,
    BashExecutorBackgroundMixin,
    BashExecutorPrepareMixin,
    BashExecutorContextMixin,
    object,
)


@pytest.mark.architecture
def test_bash_executor_mixin_mro_prefix() -> None:
    assert BashExecutor.__mro__[: len(_EXPECTED_BASH_EXECUTOR_MIXIN_MRO)] == _EXPECTED_BASH_EXECUTOR_MIXIN_MRO


@pytest.mark.architecture
def test_bash_executor_execute_resolves_to_execute_mixin() -> None:
    owner = next(c for c in BashExecutor.__mro__ if "execute" in c.__dict__)
    assert owner is BashExecutorExecuteMixin


@pytest.mark.architecture
def test_bash_executor_prepare_resolves_to_prepare_mixin() -> None:
    owner = next(c for c in BashExecutor.__mro__ if "_prepare_execution" in c.__dict__)
    assert owner is BashExecutorPrepareMixin


@pytest.mark.architecture
def test_bash_executor_spawn_background_resolves_to_background_mixin() -> None:
    owner = next(c for c in BashExecutor.__mro__ if "spawn_background" in c.__dict__)
    assert owner is BashExecutorBackgroundMixin
