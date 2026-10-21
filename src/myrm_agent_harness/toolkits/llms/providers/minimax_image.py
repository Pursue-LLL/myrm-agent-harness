"""MiniMax image-01 custom provider for LiteLLM.

[INPUT]
- litellm::CustomLLM, CustomLLMError (POS: LiteLLM custom provider base)
- litellm.types.utils::ImageResponse, ImageObject (POS: LiteLLM image response types)

[OUTPUT]
- minimax_image_llm: Registered LiteLLM custom provider instance

[POS]
Custom LiteLLM provider for MiniMax image-01 model. Handles the translation
between LiteLLM's OpenAI-compatible image_generation() API and MiniMax's
proprietary /v1/image_generation endpoint. Supports text-to-image generation
and image-to-image generation via subject_reference.
"""

from __future__ import annotations

import logging

import httpx
import litellm
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from litellm.llms.custom_llm import CustomLLM, CustomLLMError
from litellm.types.utils import ImageObject, ImageResponse

logger = logging.getLogger(__name__)

_MINIMAX_API_BASE = "https://api.minimax.io"

_SIZE_TO_ASPECT_RATIO: dict[str, str] = {
    "1024x1024": "1:1",
    "1280x720": "16:9",
    "1152x864": "4:3",
    "1248x832": "3:2",
    "832x1248": "2:3",
    "864x1152": "3:4",
    "720x1280": "9:16",
    "1344x576": "21:9",
}

_VALID_ASPECT_RATIOS = {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"}


def _resolve_aspect_ratio(size: str | None) -> str:
    """Convert size parameter to MiniMax aspect_ratio.

    Accepts either WxH format (e.g. "1024x1024") or direct aspect ratio
    (e.g. "16:9"). Falls back to "1:1" if unrecognized.
    """
    if not size:
        return "1:1"
    if size in _VALID_ASPECT_RATIOS:
        return size
    return _SIZE_TO_ASPECT_RATIO.get(size, "1:1")


class MiniMaxImageLLM(CustomLLM):
    """LiteLLM custom provider for MiniMax image-01 model.

    Translates LiteLLM image_generation() calls to MiniMax's
    /v1/image_generation API. Supports text-to-image and
    image-to-image (via subject_reference in extra_body).
    """

    async def aimage_generation(
        self,
        model: str,
        prompt: str,
        model_response: ImageResponse,
        optional_params: dict[str, object],
        logging_obj: object,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        client: AsyncHTTPHandler | None = None,
    ) -> ImageResponse:
        """Generate images via MiniMax API."""
        base_url = (api_base or _MINIMAX_API_BASE).rstrip("/")
        key = api_key or ""
        if not key:
            raise CustomLLMError(status_code=401, message="Missing api_key for MiniMax")

        model_name = model.split("/", 1)[-1] if "/" in model else model

        payload: dict[str, object] = {
            "model": model_name,
            "prompt": prompt,
            "aspect_ratio": _resolve_aspect_ratio(str(optional_params.get("size", ""))),
            "response_format": "url",
        }

        n = optional_params.get("n")
        if isinstance(n, int) and n > 1:
            payload["n"] = n

        extra_body = optional_params.get("extra_body")
        if isinstance(extra_body, dict):
            if "subject_reference" in extra_body:
                payload["subject_reference"] = extra_body["subject_reference"]
            if "prompt_optimizer" in extra_body:
                payload["prompt_optimizer"] = extra_body["prompt_optimizer"]
            if "seed" in extra_body:
                payload["seed"] = extra_body["seed"]

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        effective_timeout: float | httpx.Timeout = timeout or httpx.Timeout(120)
        http_client = client or AsyncHTTPHandler(timeout=effective_timeout)
        created_client = client is None

        try:
            resp = await http_client.post(
                f"{base_url}/v1/image_generation",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if created_client:
                await http_client.close()

        base_resp = data.get("base_resp", {})
        status_code = base_resp.get("status_code", -1)
        if status_code != 0:
            raise CustomLLMError(
                status_code=_map_minimax_error(status_code),
                message=f"MiniMax error {status_code}: {base_resp.get('status_msg', 'unknown')}",
            )

        image_data = data.get("data", {})
        image_urls: list[str] = image_data.get("image_urls", [])
        image_b64s: list[str] = image_data.get("image_base64", [])

        images: list[ImageObject] = []
        for url in image_urls:
            images.append(ImageObject(url=url))
        for b64 in image_b64s:
            images.append(ImageObject(b64_json=b64))

        model_response.data = images
        return model_response


def _map_minimax_error(status_code: int) -> int:
    """Map MiniMax status_code to HTTP status code."""
    mapping = {
        1002: 429,  # Rate limit
        1004: 401,  # Auth failed
        1008: 402,  # Insufficient balance
        1026: 400,  # Sensitive content
        2013: 400,  # Invalid params
        2049: 401,  # Invalid API key
    }
    return mapping.get(status_code, 500)


minimax_image_llm = MiniMaxImageLLM()
litellm.custom_provider_map.append({"provider": "minimax_image", "custom_handler": minimax_image_llm})
