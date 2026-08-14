"""Local persistent session sandbox integration tests.

[INPUT]
- code_execution.sandbox (POS: Sandbox detection, policy and provider selection)
- code_execution.session.local_session (POS: Concrete local session with OS-level sandbox support)

[OUTPUT]
- Sandbox-enabled branch coverage: native provider, wrap_command fallback, provider cleanup, factory.

[POS]
Verifies the sandbox integration branches of ``LocalPersistentSession`` that the real
``auto`` detection skips on a plain developer machine (native provider path, wrap fallback,
provider cleanup, public factory).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.code_execution.sandbox import (
    SandboxStatus,
)
from myrm_agent_harness.toolkits.code_execution.session.local_session import (
    LocalPersistentSession,
    create_persistent_session,
)
from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
    SessionConfig,
)


class _FakeSandboxProvider:
    """Minimal SandboxProvider stub recording call sites."""

    name = "fake-sandbox"

    def __init__(self) -> None:
        self.create_process = AsyncMock(return_value=None)
        self.wrap_calls: list[dict[str, object]] = []
        self.cleanup_called = False

    def wrap_command(self, **kwargs: object) -> tuple[str, tuple[str, ...]]:
        self.wrap_calls.append(kwargs)
        return str(kwargs["shell_path"]), tuple(kwargs["shell_args"])  # type: ignore[arg-type]

    def cleanup(self) -> None:
        self.cleanup_called = True


def _make_config() -> SessionConfig:
    return SessionConfig(
        session_id="sandbox-test",
        work_dir="/tmp",
        sandbox_mode="disable",
    )


def _enable_fake_provider(monkeypatch: pytest.MonkeyPatch, provider: _FakeSandboxProvider) -> None:
    status = SandboxStatus(True, provider.name, "enabled")
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider",
        lambda mode, platform_info: (provider, status),
    )


@pytest.mark.asyncio
async def test_create_process_uses_native_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox-enabled path returns the native process from the provider."""
    provider = _FakeSandboxProvider()
    fake_native = AsyncMock()
    provider.create_process = AsyncMock(return_value=fake_native)
    _enable_fake_provider(monkeypatch, provider)

    session = LocalPersistentSession(_make_config())
    try:
        proc = await session._create_process()
        assert proc is fake_native
        assert provider.create_process.called
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_create_process_falls_back_to_wrap_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider returning None falls back to wrap_command and spawns a real shell."""
    provider = _FakeSandboxProvider()
    _enable_fake_provider(monkeypatch, provider)

    session = LocalPersistentSession(_make_config())
    try:
        proc = await session._create_process()
        assert proc is not None
        assert provider.wrap_calls, "wrap_command must run when provider returns None"
        assert proc.pid is not None
        proc.kill()
        await proc.wait()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_close_cleans_up_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session close propagates cleanup to the sandbox provider."""
    provider = _FakeSandboxProvider()
    _enable_fake_provider(monkeypatch, provider)

    session = LocalPersistentSession(_make_config())
    await session.close()
    assert provider.cleanup_called


def test_factory_returns_local_session() -> None:
    """create_persistent_session wires a LocalPersistentSession."""
    import asyncio

    session = create_persistent_session(_make_config())
    assert isinstance(session, LocalPersistentSession)
    assert session.config.sandbox_mode == "disable"
    asyncio.run(session.close())
