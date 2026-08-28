"""Responses wire invocation helpers for ChatLiteLLM mixins."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from myrm_agent_harness.toolkits.llms.adapters.wire.normalizer import (
    assert_responses_payload_not_failed,
    extract_responses_stream_error,
    responses_dict_to_chat_completion,
    responses_event_to_completion_chunk,
    ResponsesStreamError,
)
from myrm_agent_harness.toolkits.llms.adapters.wire.params import build_responses_kwargs

logger = logging.getLogger(__name__)


def _event_to_dict(event: object) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return dict(event.model_dump())
    if hasattr(event, "dict"):
        return dict(event.dict())
    event_type = getattr(event, "type", None)
    delta = getattr(event, "delta", None)
    response = getattr(event, "response", None)
    error = getattr(event, "error", None)
    payload: dict[str, Any] = {"type": str(event_type) if event_type is not None else type(event).__name__}
    if delta is not None:
        payload["delta"] = delta
    if error is not None:
        payload["error"] = dict(error.model_dump()) if hasattr(error, "model_dump") else error
    if response is not None:
        payload["response"] = (
            dict(response.model_dump()) if hasattr(response, "model_dump") else response
        )
    return payload


def _is_invalid_encrypted_content_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "invalid_encrypted_content" in text


def _strip_reasoning_replay(message_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for msg in message_dicts:
        if not isinstance(msg, dict):
            continue
        if "responses_reasoning_items" not in msg:
            stripped.append(msg)
            continue
        copy = dict(msg)
        copy.pop("responses_reasoning_items", None)
        stripped.append(copy)
    return stripped


def _strip_reasoning_include(params: dict[str, Any]) -> dict[str, Any]:
    params_copy = dict(params)
    extra_body = params_copy.get("extra_body")
    if not isinstance(extra_body, dict):
        return params_copy
    extra_copy = dict(extra_body)
    extra_copy.pop("include", None)
    params_copy["extra_body"] = extra_copy
    return params_copy


def _response_to_dict(response: object) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return dict(response.model_dump())
    if isinstance(response, dict):
        return response
    return {"output_text": getattr(response, "output_text", "")}


def invoke_responses_sync(client: Any, message_dicts: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    responses_kwargs = build_responses_kwargs(message_dicts, params)
    try:
        response = client.responses(**responses_kwargs)
    except Exception as exc:
        if not _is_invalid_encrypted_content_error(exc):
            raise
        logger.warning("Responses reasoning replay rejected; retrying without include/replay items")
        fallback_messages = _strip_reasoning_replay(message_dicts)
        fallback_params = _strip_reasoning_include(params)
        response = client.responses(**build_responses_kwargs(fallback_messages, fallback_params))
    response_dict = _response_to_dict(response)
    assert_responses_payload_not_failed(response_dict)
    return responses_dict_to_chat_completion(response_dict)


async def invoke_responses_async(
    client: Any,
    message_dicts: list[dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    responses_kwargs = build_responses_kwargs(message_dicts, params)
    try:
        response = await client.aresponses(**responses_kwargs)
    except Exception as exc:
        if not _is_invalid_encrypted_content_error(exc):
            raise
        logger.warning("Responses reasoning replay rejected; retrying without include/replay items")
        fallback_messages = _strip_reasoning_replay(message_dicts)
        fallback_params = _strip_reasoning_include(params)
        response = await client.aresponses(**build_responses_kwargs(fallback_messages, fallback_params))
    response_dict = _response_to_dict(response)
    assert_responses_payload_not_failed(response_dict)
    return responses_dict_to_chat_completion(response_dict)


def _iter_responses_stream(
    client: Any,
    message_dicts: list[dict[str, Any]],
    params: dict[str, Any],
) -> Iterator[object]:
    responses_kwargs = build_responses_kwargs(message_dicts, {**params, "stream": True})
    try:
        yield from client.responses(**responses_kwargs)
    except Exception as exc:
        if not _is_invalid_encrypted_content_error(exc):
            raise
        logger.warning("Responses reasoning replay rejected; retrying stream without include/replay items")
        fallback_messages = _strip_reasoning_replay(message_dicts)
        fallback_params = _strip_reasoning_include(params)
        yield from client.responses(**build_responses_kwargs(fallback_messages, {**fallback_params, "stream": True}))


async def _aiter_responses_stream(
    client: Any,
    message_dicts: list[dict[str, Any]],
    params: dict[str, Any],
) -> AsyncIterator[object]:
    responses_kwargs = build_responses_kwargs(message_dicts, {**params, "stream": True})
    try:
        stream = await client.aresponses(**responses_kwargs)
    except Exception as exc:
        if not _is_invalid_encrypted_content_error(exc):
            raise
        logger.warning("Responses reasoning replay rejected; retrying stream without include/replay items")
        fallback_messages = _strip_reasoning_replay(message_dicts)
        fallback_params = _strip_reasoning_include(params)
        stream = await client.aresponses(
            **build_responses_kwargs(fallback_messages, {**fallback_params, "stream": True})
        )
    async for event in stream:
        yield event


async def stream_responses_async(
    client: Any,
    message_dicts: list[dict[str, Any]],
    params: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    async for event in _aiter_responses_stream(client, message_dicts, params):
        event_dict = _event_to_dict(event)
        error_message = extract_responses_stream_error(event_dict)
        if error_message:
            raise ResponsesStreamError(error_message)
        chunk = responses_event_to_completion_chunk(event_dict)
        if chunk is not None:
            yield chunk


def stream_responses_sync(
    client: Any,
    message_dicts: list[dict[str, Any]],
    params: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    for event in _iter_responses_stream(client, message_dicts, params):
        event_dict = _event_to_dict(event)
        error_message = extract_responses_stream_error(event_dict)
        if error_message:
            raise ResponsesStreamError(error_message)
        chunk = responses_event_to_completion_chunk(event_dict)
        if chunk is not None:
            yield chunk
