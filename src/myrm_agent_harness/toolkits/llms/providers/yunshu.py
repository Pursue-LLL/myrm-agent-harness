"""[INPUT]
- (none)

[OUTPUT]
- YunshuLLM: - ToolCall (tools, tool_choice)

[POS]
Provides YunshuLLM.
"""

import json
from typing import Any

import httpx
import litellm
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from litellm.llms.custom_llm import CustomLLM, CustomLLMError
from litellm.types.utils import GenericStreamingChunk, ModelResponse

DEFAULT_BASE_URL = "http://yunshu.koolearn.com/yunshu/openai/v1/"
DEFAULT_USER_AGENT = "YunShu-AI-SDK/2.1"
DEFAULT_API_KEY = ""


class YunshuLLM(CustomLLM):
    """LiteLLM custom Provider：对接yunshu OpenAI compatible /v1/chat/completions。

    Support功能：
    - ToolCall (tools, tool_choice)
    - 结构化output (response_format)
    - 流式 and 非流式output
    - complete OpenAIcompatible性
    """

    def __init__(self) -> None:
        super().__init__()

    def _prepare_payload(self, model: str, messages: list, optional_params: dict) -> dict:
        """准备Request载荷 通用Method"""
        payload = {
            "model": model.split("/", 1)[-1],
            "messages": messages,
            "temperature": optional_params.get("temperature", 0.2),
        }

        #  directly 透传AllParameter，除了系统Internal using  Parameter
        exclude_params = {"api_base", "api_key"}
        for param, value in optional_params.items():
            if param not in exclude_params and not param.startswith("_"):
                payload[param] = value

        return payload

    def _prepare_headers(self, api_key: str, headers: dict | None = None) -> dict:
        """准备Request头 通用Method"""
        req_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        if headers:
            for hk, hv in headers.items():
                if hk.lower() not in {"authorization", "content-type"}:
                    req_headers[hk] = hv

        return req_headers

    def _extract_auth_info(self, api_base: str | None, api_key: str | None, optional_params: dict) -> tuple:
        """ExtractAuthenticationinformation"""
        base_url = (api_base or optional_params.get("api_base") or DEFAULT_BASE_URL).rstrip("/")
        key = (api_key or optional_params.get("api_key") or DEFAULT_API_KEY).strip()

        if not key:
            raise CustomLLMError(status_code=401, message="Missing api_key for Yunshu provider")

        return base_url, key

    async def acompletion(
        self,
        model: str,
        messages: list,
        api_base: str | None,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose,
        encoding,
        api_key: str | None,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers: dict | None = None,
        timeout: float | httpx.Timeout | None = None,
        client: AsyncHTTPHandler | None = None,
    ) -> ModelResponse:  # type: ignore[override]
        optional_params = optional_params or {}

        # ExtractAuthenticationinformation
        base_url, key = self._extract_auth_info(api_base, api_key, optional_params)

        # 准备Request
        url = f"{base_url}/chat/completions"
        req_headers = self._prepare_headers(key, headers)
        payload = self._prepare_payload(model, messages, optional_params)

        # 添加extra_body
        extra_body = optional_params.get("extra_body")
        if extra_body and isinstance(extra_body, dict):
            payload.update(extra_body)

        # SendRequest
        _timeout = timeout or httpx.Timeout(60)
        _client = client or AsyncHTTPHandler(timeout=_timeout)
        created_client = client is None
        try:
            resp = await _client.post(url, json=payload, headers=req_headers)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if created_client:
                await _client.close()

        # ProcessResponseData
        choices = []
        if isinstance(data, dict) and data.get("choices"):
            for choice in data["choices"]:
                if isinstance(choice, dict):
                    msg = choice.get("message") or {}
                    if isinstance(msg, dict):
                        choice_data = {
                            "index": choice.get("index", 0),
                            "finish_reason": choice.get("finish_reason", "stop"),
                            "message": {
                                "role": msg.get("role", "assistant"),
                                "content": msg.get("content", ""),
                            },
                        }

                        # ProcessToolCall
                        tool_calls = msg.get("tool_calls")
                        if tool_calls:
                            choice_data["message"]["tool_calls"] = tool_calls

                        choices.append(choice_data)

        if not choices:
            # DefaultEmptyResponse
            choices = [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": ""},
                }
            ]

        # 构造standard ModelResponse
        response_data = {
            "model": model,
            "stream": False,
            "choices": choices,
        }

        # 添加usageinformation
        if isinstance(data, dict) and data.get("usage"):
            response_data["usage"] = data["usage"]

        return ModelResponse(**response_data)

    async def astreaming(
        self,
        model: str,
        messages: list,
        api_base: str | None,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose,
        encoding,
        api_key: str | None,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers: dict | None = None,
        timeout: float | httpx.Timeout | None = None,
        client: AsyncHTTPHandler | None = None,
    ) -> Any:  # type: ignore[override]
        optional_params = optional_params or {}

        # ExtractAuthenticationinformation
        base_url, key = self._extract_auth_info(api_base, api_key, optional_params)

        # 准备流式Request头
        url = f"{base_url}/chat/completions"
        req_headers = self._prepare_headers(key, headers)
        req_headers.update(
            {
                "Accept": "text/event-stream",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Connection": "keep-alive",
            }
        )

        # 准备流式载荷
        payload = self._prepare_payload(model, messages, optional_params)
        payload["stream"] = True

        # Send流式Request
        _timeout = timeout or httpx.Timeout(60)
        _client = client or AsyncHTTPHandler(timeout=_timeout)
        created_client = client is None
        response = await _client.post(url, json=payload, headers=req_headers, stream=True)
        try:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                    delta_text = ""
                    tool_use = None
                    finish_reason = ""

                    if isinstance(event, dict) and event.get("choices"):
                        choice0 = event["choices"][0]
                        if isinstance(choice0, dict):
                            delta = choice0.get("delta") or {}
                            finish_reason = choice0.get("finish_reason", "")

                            if isinstance(delta, dict):
                                delta_text = delta.get("content") or ""

                                # ProcessToolCall增量
                                tool_calls = delta.get("tool_calls")
                                if tool_calls and isinstance(tool_calls, list):
                                    # simplifiedToolCallProcess，传递originaltool_calls
                                    tool_use = tool_calls[0] if tool_calls else None

                    chunk: GenericStreamingChunk = {
                        "finish_reason": finish_reason,
                        "index": 0,
                        "is_finished": bool(finish_reason),
                        "text": delta_text,
                        "tool_use": tool_use,
                        "usage": None,
                    }
                    yield chunk
                except Exception:
                    continue
        finally:
            await response.aclose()
            if created_client:
                await _client.close()

        final_chunk: GenericStreamingChunk = {
            "finish_reason": "stop",
            "index": 0,
            "is_finished": True,
            "text": "",
            "tool_use": None,
            "usage": None,
        }
        yield final_chunk


# Instance化并Register to  LiteLLM
yunshu_llm = YunshuLLM()
litellm.custom_provider_map.append({"provider": "yunshu", "custom_handler": yunshu_llm})
