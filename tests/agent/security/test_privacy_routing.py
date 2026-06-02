"""Tests for PrivacyRoutingModel — privacy-aware LLM routing logic."""

from collections.abc import AsyncIterator, Iterator
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from myrm_agent_harness.agent.security.types import PrivacyRoutingConfig, SensitivityLevel
from myrm_agent_harness.toolkits.llms.routing.privacy_routing import PrivacyRoutingModel

_TRACKER_PATCH = "myrm_agent_harness.core.security.guards.privacy_tracker.get_privacy_tracker"


class _FakeModel(BaseChatModel):
    """Minimal BaseChatModel subclass for testing."""

    name: str = "fake"
    _sync_result: str = "sync-ok"
    _async_result: str = "async-ok"
    _stream_chunks: list[str] | None = None
    _side_effect: BaseException | None = None

    @property
    def _llm_type(self) -> str:
        return self.name

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs: object) -> ChatResult:
        if self._side_effect is not None:
            raise self._side_effect
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._sync_result))])

    async def _agenerate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs: object
    ) -> ChatResult:
        if self._side_effect is not None:
            raise self._side_effect
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._async_result))])

    def _stream(
        self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs: object
    ) -> Iterator[ChatGenerationChunk]:
        if self._side_effect is not None:
            raise self._side_effect
        chunks = self._stream_chunks or [self._sync_result]
        for text in chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))

    async def _astream(
        self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs: object
    ) -> AsyncIterator[ChatGenerationChunk]:
        if self._side_effect is not None:
            raise self._side_effect
        chunks = self._stream_chunks or [self._async_result]
        for text in chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))


def _make_router(
    s2_strategy: str = "cloud_after_redact",
    s3_strategy: str = "local",
    local_fallback: str = "block",
    cloud_sync: str = "cloud-sync",
    cloud_async: str = "cloud-async",
    local_sync: str = "local-sync",
    local_async: str = "local-async",
) -> PrivacyRoutingModel:
    cloud = _FakeModel(name="cloud")
    cloud._sync_result = cloud_sync
    cloud._async_result = cloud_async
    local = _FakeModel(name="local")
    local._sync_result = local_sync
    local._async_result = local_async
    return PrivacyRoutingModel(
        cloud_llm=cloud,
        local_llm=local,
        routing_config=PrivacyRoutingConfig(
            local_model="ollama/test",
            s2_strategy=s2_strategy,  # type: ignore[arg-type]
            s3_strategy=s3_strategy,  # type: ignore[arg-type]
            local_fallback=local_fallback,  # type: ignore[arg-type]
        ),
    )


def _mock_tracker(level: SensitivityLevel) -> MagicMock:
    tracker = MagicMock()
    tracker.current_turn_level = level
    return tracker


class TestResolveTarget:
    """Test _resolve_target routing decisions."""

    @patch(_TRACKER_PATCH)
    def test_s1_routes_to_cloud(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S1)
        router = _make_router()
        target, label = router._resolve_target()
        assert target is router.cloud_llm
        assert "cloud" in label

    @patch(_TRACKER_PATCH)
    def test_s2_cloud_after_redact(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router(s2_strategy="cloud_after_redact")
        target, label = router._resolve_target()
        assert target is router.cloud_llm
        assert "s2_after_redact" in label

    @patch(_TRACKER_PATCH)
    def test_s2_local_strategy(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router(s2_strategy="local")
        target, label = router._resolve_target()
        assert target is router.local_llm
        assert "local" in label

    @patch(_TRACKER_PATCH)
    def test_s3_local(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local")
        target, label = router._resolve_target()
        assert target is router.local_llm
        assert "s3_forced" in label

    @patch(_TRACKER_PATCH)
    def test_s3_block_routes_to_cloud(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="block")
        target, label = router._resolve_target()
        assert target is router.cloud_llm
        assert "s3_block" in label

    def test_no_local_always_cloud(self):
        router = PrivacyRoutingModel(cloud_llm=_FakeModel(name="cloud"))
        target, label = router._resolve_target()
        assert target is router.cloud_llm
        assert "no_local_configured" in label


class TestGenerate:
    """Test _generate and _agenerate with routing."""

    @patch(_TRACKER_PATCH)
    def test_sync_routes_to_cloud_on_s1(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S1)
        router = _make_router()
        result = router._generate([HumanMessage(content="hello")])
        assert result.generations[0].text == "cloud-sync"

    @patch(_TRACKER_PATCH)
    def test_sync_routes_to_local_on_s3(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local")
        result = router._generate([HumanMessage(content="secret")])
        assert result.generations[0].text == "local-sync"

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_async_routes_to_cloud_on_s1(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S1)
        router = _make_router()
        result = await router._agenerate([HumanMessage(content="hello")])
        assert result.generations[0].text == "cloud-async"

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_async_routes_to_local_on_s2_local(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router(s2_strategy="local")
        result = await router._agenerate([HumanMessage(content="sensitive")])
        assert result.generations[0].text == "local-async"


class TestLocalFailure:
    """Test local model failure and fallback behavior."""

    @patch(_TRACKER_PATCH)
    def test_fallback_block_raises(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local", local_fallback="block")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")

        with pytest.raises(RuntimeError, match="Local model unavailable"):
            router._generate([HumanMessage(content="secret")])

    @patch(_TRACKER_PATCH)
    def test_fallback_force_redact_cloud(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router(s2_strategy="local", local_fallback="force_redact_cloud")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")

        result = router._generate([HumanMessage(content="sensitive")])
        assert result.generations[0].text == "cloud-sync"

    @patch(_TRACKER_PATCH)
    def test_fallback_force_redact_blocked_by_s3(self, mock_fn: MagicMock):
        """If local fails and fallback is force_redact_cloud but content is S3, block."""
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local", local_fallback="force_redact_cloud")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")

        with pytest.raises(RuntimeError, match="S3 content detected"):
            router._generate([HumanMessage(content="top-secret")])

    @patch(_TRACKER_PATCH)
    def test_local_retry_then_succeed(self, mock_fn: MagicMock):
        """Local model fails on first attempt but succeeds on retry."""
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local")
        assert isinstance(router.local_llm, _FakeModel)

        call_count = 0

        def _flaky_generate(*args: object, **kwargs: object) -> ChatResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="local-retry-ok"))])

        router.local_llm._generate = _flaky_generate  # type: ignore[assignment]
        result = router._generate([HumanMessage(content="secret")])
        assert result.generations[0].text == "local-retry-ok"
        assert call_count == 2


class _BindableModel(_FakeModel):
    """FakeModel that supports bind_tools by returning self."""

    def bind_tools(self, tools: object, **kwargs: object) -> "_BindableModel":
        return self


class _UnbindableModel(_FakeModel):
    """FakeModel that raises on bind_tools."""

    def bind_tools(self, tools: object, **kwargs: object) -> "_UnbindableModel":
        raise NotImplementedError("unsupported")


class TestBindTools:
    def test_bind_tools_propagates(self):
        cloud = _BindableModel(name="cloud")
        local = _BindableModel(name="local")
        router = PrivacyRoutingModel(cloud_llm=cloud, local_llm=local)
        tools = [{"name": "test_tool", "description": "test", "parameters": {}}]
        bound = router.bind_tools(tools)
        assert isinstance(bound, PrivacyRoutingModel)

    def test_bind_tools_local_failure_graceful(self):
        cloud = _BindableModel(name="cloud")
        local = _UnbindableModel(name="local")
        router = PrivacyRoutingModel(cloud_llm=cloud, local_llm=local)
        tools = [{"name": "test_tool", "description": "test", "parameters": {}}]
        bound = router.bind_tools(tools)
        assert isinstance(bound, PrivacyRoutingModel)


class TestProperties:
    def test_llm_type(self):
        router = _make_router()
        assert router._llm_type == "privacy-routing"

    def test_identifying_params(self):
        router = _make_router()
        params = router._identifying_params
        assert params["cloud_model"] == "cloud"
        assert params["local_model"] == "local"
        assert params["routing_config"]["s2_strategy"] == "cloud_after_redact"

    def test_identifying_params_no_local(self):
        router = PrivacyRoutingModel(cloud_llm=_FakeModel(name="cloud"))
        params = router._identifying_params
        assert params["local_model"] is None


class TestTransparentMode:
    """When local_llm is None, all calls go to cloud with zero overhead."""

    def test_generate_passthrough(self):
        cloud = _FakeModel(name="cloud")
        cloud._sync_result = "cloud-only"
        router = PrivacyRoutingModel(cloud_llm=cloud)
        result = router._generate([HumanMessage(content="hello")])
        assert result.generations[0].text == "cloud-only"

    @pytest.mark.asyncio
    async def test_agenerate_passthrough(self):
        cloud = _FakeModel(name="cloud")
        cloud._async_result = "cloud-only-async"
        router = PrivacyRoutingModel(cloud_llm=cloud)
        result = await router._agenerate([HumanMessage(content="hello")])
        assert result.generations[0].text == "cloud-only-async"

    def test_stream_passthrough(self):
        cloud = _FakeModel(name="cloud")
        cloud._stream_chunks = ["chunk1", "chunk2"]
        router = PrivacyRoutingModel(cloud_llm=cloud)
        chunks = list(router._stream([HumanMessage(content="hello")]))
        assert [c.text for c in chunks] == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_astream_passthrough(self):
        cloud = _FakeModel(name="cloud")
        cloud._stream_chunks = ["a1", "a2"]
        router = PrivacyRoutingModel(cloud_llm=cloud)
        chunks = [c async for c in router._astream([HumanMessage(content="hello")])]
        assert [c.text for c in chunks] == ["a1", "a2"]


class TestStream:
    """Test _stream routing (sync streaming)."""

    @patch(_TRACKER_PATCH)
    def test_stream_routes_to_cloud_on_s1(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S1)
        router = _make_router()
        assert isinstance(router.cloud_llm, _FakeModel)
        router.cloud_llm._stream_chunks = ["c1", "c2"]
        chunks = list(router._stream([HumanMessage(content="hello")]))
        assert [c.text for c in chunks] == ["c1", "c2"]

    @patch(_TRACKER_PATCH)
    def test_stream_routes_to_local_on_s3(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._stream_chunks = ["l1", "l2"]
        chunks = list(router._stream([HumanMessage(content="secret")]))
        assert [c.text for c in chunks] == ["l1", "l2"]

    @patch(_TRACKER_PATCH)
    def test_stream_local_failure_fallback_cloud(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router(s2_strategy="local", local_fallback="force_redact_cloud")
        assert isinstance(router.local_llm, _FakeModel)
        assert isinstance(router.cloud_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")
        router.cloud_llm._stream_chunks = ["fallback1"]
        chunks = list(router._stream([HumanMessage(content="sensitive")]))
        assert [c.text for c in chunks] == ["fallback1"]

    @patch(_TRACKER_PATCH)
    def test_stream_local_failure_block_raises(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local", local_fallback="block")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")
        with pytest.raises(RuntimeError, match="Local model unavailable"):
            list(router._stream([HumanMessage(content="secret")]))


class TestAStream:
    """Test _astream routing (async streaming)."""

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_astream_routes_to_cloud_on_s1(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S1)
        router = _make_router()
        assert isinstance(router.cloud_llm, _FakeModel)
        router.cloud_llm._stream_chunks = ["ac1", "ac2"]
        chunks = [c async for c in router._astream([HumanMessage(content="hello")])]
        assert [c.text for c in chunks] == ["ac1", "ac2"]

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_astream_routes_to_local_on_s3(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._stream_chunks = ["al1", "al2"]
        chunks = [c async for c in router._astream([HumanMessage(content="secret")])]
        assert [c.text for c in chunks] == ["al1", "al2"]

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_astream_local_failure_fallback_cloud(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router(s2_strategy="local", local_fallback="force_redact_cloud")
        assert isinstance(router.local_llm, _FakeModel)
        assert isinstance(router.cloud_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")
        router.cloud_llm._stream_chunks = ["afb1"]
        chunks = [c async for c in router._astream([HumanMessage(content="sensitive")])]
        assert [c.text for c in chunks] == ["afb1"]

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_astream_local_failure_block_raises(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local", local_fallback="block")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")
        with pytest.raises(RuntimeError, match="Local model unavailable"):
            _ = [c async for c in router._astream([HumanMessage(content="secret")])]


class TestAsyncLocalFailure:
    """Test _agenerate local model failure + fallback (async path)."""

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_agenerate_fallback_block_raises(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local", local_fallback="block")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")
        with pytest.raises(RuntimeError, match="Local model unavailable"):
            await router._agenerate([HumanMessage(content="secret")])

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_agenerate_fallback_force_redact_cloud(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router(s2_strategy="local", local_fallback="force_redact_cloud")
        assert isinstance(router.local_llm, _FakeModel)
        router.local_llm._side_effect = ConnectionError("offline")
        result = await router._agenerate([HumanMessage(content="sensitive")])
        assert result.generations[0].text == "cloud-async"

    @pytest.mark.asyncio
    @patch(_TRACKER_PATCH)
    async def test_agenerate_retry_then_succeed(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local")
        assert isinstance(router.local_llm, _FakeModel)

        call_count = 0

        async def _flaky_agenerate(*args: object, **kwargs: object) -> ChatResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="async-retry-ok"))])

        router.local_llm._agenerate = _flaky_agenerate  # type: ignore[assignment]
        result = await router._agenerate([HumanMessage(content="secret")])
        assert result.generations[0].text == "async-retry-ok"
        assert call_count == 2


class TestRecordRoutingDecision:
    """Test _record_routing_decision audit + SSE logic."""

    @patch("myrm_agent_harness.toolkits.llms.routing.privacy_routing.logger")
    @patch(_TRACKER_PATCH)
    def test_cloud_route_no_sse(self, mock_tracker_fn: MagicMock, mock_logger: MagicMock):
        """Cloud route should NOT emit SSE event (only local routes do)."""
        mock_tracker_fn.return_value = _mock_tracker(SensitivityLevel.S1)
        router = _make_router()
        router._generate([HumanMessage(content="hello")])
        mock_logger.info.assert_called()

    @patch(_TRACKER_PATCH)
    def test_local_route_attempts_sse(self, mock_fn: MagicMock):
        """Local route should attempt SSE event emission without error."""
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router(s3_strategy="local")
        result = router._generate([HumanMessage(content="secret")])
        assert result.generations[0].text == "local-sync"

    def test_record_routing_graceful_on_missing_audit(self):
        """_record_routing_decision should not raise even if audit module fails."""
        router = _make_router()
        router._record_routing_decision("cloud(s1_safe)")

    def test_record_routing_graceful_on_missing_sink(self):
        """_record_routing_decision should not raise even if progress sink is unavailable."""
        router = _make_router()
        router._record_routing_decision("local(s3_forced)")


class TestVerifyRedactionSafety:
    """Test _verify_redaction_safety independently."""

    @patch(_TRACKER_PATCH)
    def test_s3_raises(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S3)
        router = _make_router()
        with pytest.raises(RuntimeError, match="S3 content detected"):
            router._verify_redaction_safety()

    @patch(_TRACKER_PATCH)
    def test_s2_passes(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S2)
        router = _make_router()
        router._verify_redaction_safety()

    @patch(_TRACKER_PATCH)
    def test_s1_passes(self, mock_fn: MagicMock):
        mock_fn.return_value = _mock_tracker(SensitivityLevel.S1)
        router = _make_router()
        router._verify_redaction_safety()


class TestPrivacyRoutingConfigDefaults:
    """Test PrivacyRoutingConfig default values."""

    def test_defaults(self):
        cfg = PrivacyRoutingConfig()
        assert cfg.local_model is None
        assert cfg.local_base_url is None
        assert cfg.local_api_key is None
        assert cfg.s2_strategy == "cloud_after_redact"
        assert cfg.s3_strategy == "local"
        assert cfg.local_fallback == "block"

    def test_frozen(self):
        cfg = PrivacyRoutingConfig(local_model="test")
        with pytest.raises(AttributeError):
            cfg.local_model = "changed"  # type: ignore[misc]

    def test_custom_values(self):
        cfg = PrivacyRoutingConfig(
            local_model="ollama/llama3",
            local_base_url="http://localhost:11434",
            local_api_key="key123",
            s2_strategy="local",
            s3_strategy="block",
            local_fallback="force_redact_cloud",
        )
        assert cfg.local_model == "ollama/llama3"
        assert cfg.local_base_url == "http://localhost:11434"
        assert cfg.local_api_key == "key123"
        assert cfg.s2_strategy == "local"
        assert cfg.s3_strategy == "block"
        assert cfg.local_fallback == "force_redact_cloud"
