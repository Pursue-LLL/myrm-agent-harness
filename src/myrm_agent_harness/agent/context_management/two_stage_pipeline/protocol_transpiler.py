"""Phase 2: Protocol conversion transpiling high-level logical context to provider-specific payloads.

[INPUT]
- agent.context_management.two_stage_pipeline.pipeline_types::AssemblyAdjustmentDirective,
  LlmProviderProtocolKind, LogicalContextBundle, LogicalTurn, ProviderPayloadResult (POS: Strong types and
  schemas for two-stage context assembly and provider protocol decoupling.)

[OUTPUT]
- ProviderProtocolTranspiler: Translates provider-agnostic LogicalContextBundle into wire-ready schemas for
  major LLM vendors.

[POS]
Phase 2: Protocol conversion transpiling high-level logical context to provider-specific payloads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional, Tuple

from .pipeline_types import (
    AssemblyAdjustmentDirective,
    LlmProviderProtocolKind,
    LogicalContextBundle,
    LogicalTurn,
    ProviderPayloadResult,
)


class ProviderProtocolTranspiler:
    """Translates provider-agnostic LogicalContextBundle into wire-ready schemas for major LLM vendors."""

    @classmethod
    def transpile_to_provider(
        cls,
        bundle: LogicalContextBundle,
        provider: LlmProviderProtocolKind,
    ) -> Tuple[ProviderPayloadResult, Optional[AssemblyAdjustmentDirective]]:
        """Convert logical context to specific provider wire payload."""
        combined_system = "\n\n".join(bundle.system_directives).strip()

        if provider == LlmProviderProtocolKind.ANTHROPIC:
            return cls._transpile_anthropic(bundle, combined_system)
        elif provider == LlmProviderProtocolKind.OPENAI:
            return cls._transpile_openai(bundle, combined_system)
        elif provider == LlmProviderProtocolKind.DEEPSEEK:
            return cls._transpile_deepseek(bundle, combined_system)
        elif provider == LlmProviderProtocolKind.GEMINI:
            return cls._transpile_gemini(bundle, combined_system)
        else:
            raise ValueError(f"Unsupported provider protocol: {provider}")

    @classmethod
    def _transpile_anthropic(
        cls,
        bundle: LogicalContextBundle,
        system_text: str,
    ) -> Tuple[ProviderPayloadResult, Optional[AssemblyAdjustmentDirective]]:
        """Map to Anthropic Messages API payload."""
        messages: List[Dict[str, str]] = []
        for turn in bundle.dialogue_turns:
            if turn.role in ("user", "assistant"):
                messages.append({"role": turn.role, "content": turn.content})
            elif turn.role == "tool":
                messages.append({"role": "user", "content": f"[Tool {turn.tool_name or ''} Result]: {turn.content}"})

        # Anthropic schema requires top-level system parameter
        wire_data: Dict[str, str] = {
            "system": system_text,
            "messages": json.dumps(messages, ensure_ascii=False),
            "max_tokens": str(bundle.max_tokens),
            "temperature": str(bundle.temperature),
        }
        if bundle.active_tools:
            tools_list = [{"name": t.name, "description": t.description} for t in bundle.active_tools]
            wire_data["tools"] = json.dumps(tools_list, ensure_ascii=False)

        encoded = json.dumps(wire_data, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

        result = ProviderPayloadResult(
            provider=LlmProviderProtocolKind.ANTHROPIC,
            payload_dict=wire_data,
            estimated_tokens=max(20, len(encoded) // 4),
            system_prompt_mode="top_level_param",
            payload_hash=payload_hash,
        )
        return result, None

    @classmethod
    def _transpile_openai(
        cls,
        bundle: LogicalContextBundle,
        system_text: str,
    ) -> Tuple[ProviderPayloadResult, Optional[AssemblyAdjustmentDirective]]:
        """Map to OpenAI Chat Completions API with developer/system roles."""
        messages: List[Dict[str, str]] = []
        if system_text:
            messages.append({"role": "developer", "content": system_text})

        for turn in bundle.dialogue_turns:
            role = turn.role
            if role not in ("developer", "system", "user", "assistant", "tool"):
                role = "user"
            messages.append({"role": role, "content": turn.content})

        wire_data: Dict[str, str] = {
            "messages": json.dumps(messages, ensure_ascii=False),
            "max_tokens": str(bundle.max_tokens),
            "temperature": str(bundle.temperature),
        }
        if bundle.active_tools:
            tools_list = [
                {"type": "function", "function": {"name": t.name, "description": t.description}}
                for t in bundle.active_tools
            ]
            wire_data["tools"] = json.dumps(tools_list, ensure_ascii=False)

        encoded = json.dumps(wire_data, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

        result = ProviderPayloadResult(
            provider=LlmProviderProtocolKind.OPENAI,
            payload_dict=wire_data,
            estimated_tokens=max(20, len(encoded) // 4),
            system_prompt_mode="developer_message",
            payload_hash=payload_hash,
        )
        return result, None

    @classmethod
    def _transpile_deepseek(
        cls,
        bundle: LogicalContextBundle,
        system_text: str,
    ) -> Tuple[ProviderPayloadResult, Optional[AssemblyAdjustmentDirective]]:
        """Map to DeepSeek API with explicit reasoning_content preservation."""
        messages: List[Dict[str, str]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})

        for turn in bundle.dialogue_turns:
            item: Dict[str, str] = {"role": turn.role, "content": turn.content}
            if turn.reasoning_content:
                item["reasoning_content"] = turn.reasoning_content
            messages.append(item)

        wire_data: Dict[str, str] = {
            "messages": json.dumps(messages, ensure_ascii=False),
            "max_tokens": str(bundle.max_tokens),
            "temperature": str(bundle.temperature),
        }
        encoded = json.dumps(wire_data, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

        result = ProviderPayloadResult(
            provider=LlmProviderProtocolKind.DEEPSEEK,
            payload_dict=wire_data,
            estimated_tokens=max(20, len(encoded) // 4),
            system_prompt_mode="system_message",
            payload_hash=payload_hash,
        )
        return result, None

    @classmethod
    def _transpile_gemini(
        cls,
        bundle: LogicalContextBundle,
        system_text: str,
    ) -> Tuple[ProviderPayloadResult, Optional[AssemblyAdjustmentDirective]]:
        """Map to Google Gemini API with system_instruction and contents parts."""
        contents: List[Dict[str, str]] = []
        for turn in bundle.dialogue_turns:
            role = "model" if turn.role == "assistant" else "user"
            part_str = json.dumps([{"text": turn.content}], ensure_ascii=False)
            contents.append({"role": role, "parts": part_str})

        wire_data: Dict[str, str] = {
            "system_instruction": json.dumps({"parts": [{"text": system_text}]}, ensure_ascii=False),
            "contents": json.dumps(contents, ensure_ascii=False),
            "temperature": str(bundle.temperature),
            "max_output_tokens": str(bundle.max_tokens),
        }
        encoded = json.dumps(wire_data, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

        result = ProviderPayloadResult(
            provider=LlmProviderProtocolKind.GEMINI,
            payload_dict=wire_data,
            estimated_tokens=max(20, len(encoded) // 4),
            system_prompt_mode="system_instruction",
            payload_hash=payload_hash,
        )
        return result, None
