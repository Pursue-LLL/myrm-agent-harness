"""Wire transport utilities for ChatLiteLLM.

[INPUT]
- None at import time; re-exports the public wire helpers consumed by ChatLiteLLM mixins

[OUTPUT]
- responses_dict_to_chat_completion / responses_event_to_completion_chunk
- build_responses_kwargs
- chat_messages_to_responses_input / resolve_min_output_tokens

[POS]
Public surface of the wire transport subpackage. Import from here rather than from the
individual modules so the internal module layout stays free to change. Harness-only
protocol layer; vendor routing tables live in server `app/core/wire/`.
"""

from myrm_agent_harness.toolkits.llms.adapters.wire.normalizer import (
    responses_dict_to_chat_completion,
    responses_event_to_completion_chunk,
)
from myrm_agent_harness.toolkits.llms.adapters.wire.params import build_responses_kwargs
from myrm_agent_harness.toolkits.llms.adapters.wire.translator import (
    chat_messages_to_responses_input,
    resolve_min_output_tokens,
)

__all__ = [
    "build_responses_kwargs",
    "chat_messages_to_responses_input",
    "resolve_min_output_tokens",
    "responses_dict_to_chat_completion",
    "responses_event_to_completion_chunk",
]
