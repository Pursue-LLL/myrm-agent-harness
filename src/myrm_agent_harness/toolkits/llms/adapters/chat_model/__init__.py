"""LangChain LiteLLM chat-model adapter sub-package.

Aggregates the aggregate root (``model``) with its generation mixins and
exception types.

[INPUT]
- langchain_core.language_models.chat_models::BaseChatModel (POS: LangChain chat model base class)
- litellm::litellm (POS: LiteLLM library)

[OUTPUT]
- model: ChatLiteLLM (LangChain-compatible LiteLLM chat model aggregate root), clean_model_kwargs
- async_mixin / sync_mixin / message_mixin: generation and message assembly mixins
- exceptions: EmptyChoicesError, EmptyStreamError, StreamStallTimeoutError, adapter constants

[POS]
LangChain LiteLLM chat-model adapter layer.
"""

from .exceptions import (
    _DEVELOPER_ROLE_PATTERN,
    EmptyChoicesError,
    EmptyStreamError,
    StreamStallTimeoutError,
)
from .model import ChatLiteLLM, clean_model_kwargs

__all__ = [
    "_DEVELOPER_ROLE_PATTERN",
    "ChatLiteLLM",
    "EmptyChoicesError",
    "EmptyStreamError",
    "StreamStallTimeoutError",
    "clean_model_kwargs",
]
