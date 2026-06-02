"""Hugging Face Inference Tool

Provides `huggingface_inference_tool` for calling HF Serverless Inference API.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.utils.errors import ToolError

logger = logging.getLogger(__name__)


class HuggingFaceInferenceInput(BaseModel):
    model_id: str = Field(
        ...,
        description="The Hugging Face model ID to use (e.g. 'stabilityai/stable-diffusion-3.5-large', 'facebook/mms-tts-eng', etc.)",
    )
    task: str = Field(
        ...,
        description="The type of task to perform. Examples: 'text-to-image', 'text-to-speech', 'text-classification', etc.",
    )
    inputs: Any = Field(
        ...,
        description="The input data for the model. For text-to-image, this is the prompt string. For classification, the text string.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional dictionary of parameters specific to the model and task (e.g. negative_prompt, num_inference_steps).",
    )


def create_huggingface_inference_tool():
    """Create the Hugging Face Inference tool."""

    @tool("huggingface_inference_tool", args_schema=HuggingFaceInferenceInput)
    async def huggingface_inference_tool(
        model_id: str,
        task: str,
        inputs: Any,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Call a Hugging Face model using the Serverless Inference API.

        Requires the HF_TOKEN environment variable to be set.
        Ideal for multi-modal generation (text-to-image, text-to-speech) and specialized classification tasks.
        """
        import httpx

        # Read token from env
        hf_token = os.environ.get("HF_TOKEN")
        if not hf_token:
            raise ToolError(
                "HF_TOKEN environment variable is not set. Please instruct the user to configure their Hugging Face Access Token in the settings."
            )

        api_url = f"https://api-inference.huggingface.co/models/{model_id}"
        headers = {
            "Authorization": f"Bearer {hf_token}",
            "Content-Type": "application/json",
        }

        payload = {"inputs": inputs}
        if parameters:
            payload["parameters"] = parameters

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(api_url, headers=headers, json=payload)

                if response.status_code == 503:
                    # Model is loading
                    error_data = response.json()
                    estimated_time = error_data.get("estimated_time", "unknown")
                    raise ToolError(
                        f"Model {model_id} is currently loading. Estimated time: {estimated_time}s. "
                        "Please wait and try again, or use a different model."
                    )

                response.raise_for_status()

                # Process the response based on content type
                content_type = response.headers.get("content-type", "")

                if content_type.startswith("image/"):
                    img_data = base64.b64encode(response.content).decode("utf-8")
                    mime_type = content_type.split(";")[0]
                    # Return markdown image representation
                    return f"![Generated Image](data:{mime_type};base64,{img_data})"
                elif content_type.startswith("audio/"):
                    audio_data = base64.b64encode(response.content).decode("utf-8")
                    mime_type = content_type.split(";")[0]
                    return f"Audio generated successfully. Base64 data (Data URI format):\ndata:{mime_type};base64,{audio_data}"
                else:
                    # Assume JSON/text response
                    try:
                        return json.dumps(response.json(), indent=2, ensure_ascii=False)
                    except Exception:
                        return response.text

        except httpx.HTTPStatusError as e:
            err_text = e.response.text
            raise ToolError(f"Hugging Face API returned error {e.response.status_code}: {err_text}") from e
        except httpx.RequestError as e:
            raise ToolError(f"Network error communicating with Hugging Face API: {e!s}") from e

    return huggingface_inference_tool
