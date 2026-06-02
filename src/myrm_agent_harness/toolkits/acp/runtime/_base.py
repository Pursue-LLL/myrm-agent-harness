"""Base class for RuntimeBackend implementations.

Encapsulates common logic shared by AcpRuntime, SdkRuntime, and CliRuntime:
environment variable sanitization, timeout control, and response truncation.

[INPUT]
- toolkits.acp.types::AcpError, AcpErrorCode, BackendCapabilities (POS: ACP runtime type definitions layer. Provides all ACP-related core abstractions and data structures, serving as the foundation for the entire ACP module.)

[OUTPUT]
- BaseRuntime: Abstract base for RuntimeBackend implementations.
- build_safe_env: Build a sanitized environment for the child process.
- truncate_response: Truncate response text if it exceeds the configured limit.

[POS]
Base class for RuntimeBackend implementations.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator

from myrm_agent_harness.toolkits.acp.types import (
    AcpError,
    AcpErrorCode,
    BackendCapabilities,
    BackendInfo,
    BackendStatus,
    BackendType,
    McpServerConfig,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeEventType,
    create_event,
)

logger = logging.getLogger(__name__)

# Provider-secret env prefixes. A delegated child must never inherit the host's
# model credentials: in subscription mode it would defeat the point (and silently
# bill the user's API key), in api_key mode it would leak unrelated providers' keys.
# Kept exhaustive across the providers our backends (Codex/Claude/Gemini/Qwen/…) reach.
_SENSITIVE_ENV_PREFIXES = frozenset(
    {
        "OPENAI_",
        "ANTHROPIC_",
        "AZURE_",
        "GOOGLE_",
        "GEMINI_",
        "VERTEX_",
        "DEEPSEEK_",
        "TOGETHER_",
        "GROQ_",
        "COHERE_",
        "MISTRAL_",
        "XAI_",
        "QWEN_",
        "DASHSCOPE_",
        "MOONSHOT_",
        "PERPLEXITY_",
        "CEREBRAS_",
        "FIREWORKS_",
        "OPENROUTER_",
        "HF_",
        "HUGGINGFACE_",
        "AWS_SECRET",
        "AWS_BEARER_TOKEN",
    }
)


def _is_sensitive_key(upper_key: str) -> bool:
    """Whether an env var name matches a known provider-secret prefix."""
    return any(upper_key.startswith(prefix) for prefix in _SENSITIVE_ENV_PREFIXES)


def build_safe_env(
    config: RuntimeConfig,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a sanitized environment for a delegated child process.

    Two layers, both honouring ``config.auth_mode``:

    1. Baseline strip — provider secrets in the parent environment (plus any in
       ``strip_env_keys``) are always removed, so a delegated CLI can never
       inherit the host's keys.
    2. Credential injection from ``config.env``:
       - ``api_key``: applied verbatim, letting the host inject the single
         provider key this backend should bill against.
       - ``subscription``: only non-secret entries are applied; injected provider
         secrets are dropped so the CLI is forced onto its own logged-in
         subscription session rather than silently falling back to a key.
    """
    env = dict(base_env or os.environ)

    explicit_strip = set(config.strip_env_keys)
    keys_to_remove = [key for key in env if key in explicit_strip or _is_sensitive_key(key.upper())]
    for key in keys_to_remove:
        del env[key]

    if config.env:
        if config.auth_mode == "subscription":
            overrides = {k: v for k, v in config.env.items() if not _is_sensitive_key(k.upper())}
            dropped = config.env.keys() - overrides.keys()
            if dropped:
                logger.warning(
                    "build_safe_env auth_mode=subscription dropped injected provider secret(s)=%s",
                    sorted(dropped),
                )
            env.update(overrides)
        else:
            env.update(config.env)

    return env


def truncate_response(text: str, max_chars: int) -> str:
    """Truncate response text if it exceeds the configured limit."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[truncated — response exceeded limit]"


class BaseRuntime:
    """Abstract base for RuntimeBackend implementations.

    Subclasses must implement ``_do_run_turn``, ``_do_cancel``, ``_do_resume``,
    ``_do_close``, and ``_do_get_status``.
    """

    def __init__(self, runtime_name: str, config: RuntimeConfig, backend_type: BackendType) -> None:
        self._name = runtime_name
        self._config = config
        self._backend_type = backend_type
        self._alive = False

    # -- Properties (satisfy RuntimeBackend Protocol) --

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities()

    @property
    def is_alive(self) -> bool:
        return self._alive

    # -- Public API --

    async def run_turn(
        self,
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Execute a turn with timeout control and streaming truncation.

        Wraps ``_do_run_turn`` with ``asyncio.timeout``, applies per-character
        truncation on TEXT_DELTA events, and emits an error event on timeout
        or unexpected failure.
        """
        char_count = 0
        max_chars = self._config.max_response_chars
        truncated = False

        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                async for event in self._do_run_turn(prompt, session_id, mcp_servers=mcp_servers):
                    if truncated:
                        if event.type == RuntimeEventType.TEXT_DELTA:
                            continue
                        yield event
                        continue

                    if event.type == RuntimeEventType.TEXT_DELTA:
                        content = event.data.get("content", "")
                        if isinstance(content, str):
                            char_count += len(content)
                            if char_count > max_chars:
                                yield create_event(
                                    RuntimeEventType.TEXT_DELTA,
                                    session_id,
                                    content="\n\n[truncated — response exceeded limit]",
                                )
                                truncated = True
                                continue

                    yield event
        except TimeoutError:
            logger.error(
                "runtime_timeout name=%s session=%s timeout=%ds", self._name, session_id, self._config.timeout_seconds
            )
            yield create_event(
                RuntimeEventType.ERROR,
                session_id,
                error=AcpError(
                    code=AcpErrorCode.TIMEOUT,
                    message=f"Agent '{self._name}' timed out after {self._config.timeout_seconds}s",
                    retryable=True,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("runtime_error name=%s session=%s error=%s", self._name, session_id, exc, exc_info=True)
            yield create_event(
                RuntimeEventType.ERROR,
                session_id,
                error=AcpError(
                    code=AcpErrorCode.UNKNOWN,
                    message=f"Agent '{self._name}' failed: {type(exc).__name__}: {exc}",
                ),
            )

    async def cancel(self, session_id: str) -> None:
        try:
            await self._do_cancel(session_id)
        except Exception:
            logger.debug("runtime_cancel_failed name=%s session=%s", self._name, session_id, exc_info=True)

    async def resume(self, session_id: str) -> bool:
        return await self._do_resume(session_id)

    async def get_info(self) -> BackendInfo:
        status = await self._do_get_status()
        return BackendInfo(
            name=self._name,
            backend_type=self._backend_type,
            status=status,
            capabilities=self.capabilities,
        )

    async def close(self) -> None:
        try:
            await self._do_close()
        except Exception:
            logger.debug("runtime_close_failed name=%s", self._name, exc_info=True)
        finally:
            self._alive = False
            logger.info("runtime_closed name=%s", self._name)

    # -- Template methods (subclasses implement) --

    async def _do_run_turn(
        self,
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        raise NotImplementedError
        yield  # pragma: no cover — makes this an async generator

    async def _do_cancel(self, session_id: str) -> None:
        pass

    async def _do_resume(self, session_id: str) -> bool:
        return False

    async def _do_close(self) -> None:
        pass

    async def _do_get_status(self) -> BackendStatus:
        return "ready" if self._alive else "stopped"
