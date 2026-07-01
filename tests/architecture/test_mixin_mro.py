"""Architecture gate: aggregate-root mixin MRO order.

BrowserSession and ChatLiteLLM rely on multiple inheritance. Wrong mixin order
silently changes which navigate/restart/bind implementation runs. These tests
lock the intended MRO prefix and method resolution owners.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

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
