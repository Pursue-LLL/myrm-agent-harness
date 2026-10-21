"""LiteLLM default configuration


[INPUT]
- litellm::litellm (POS: LiteLLM library, unified multi-model invocation interface)
- litellm.caching.caching::Cache, CacheMode, LiteLLMCacheType (POS: LiteLLM cache configuration)

[OUTPUT]
- litellm global configuration (drop_params, modify_params, telemetry, turn_off_message_logging, cache, etc.)

[POS]
LiteLLM default configuration. Sets sensible defaults for litellm (privacy protection,
logging control, caching, etc.). Configuration is auto-applied at module import time,
ensuring all LiteLLM instances use a unified configuration. As the config layer, it
affects the behavior of all LLM instances.
"""

import litellm
from litellm.caching.caching import Cache, CacheMode, LiteLLMCacheType

# Global safety-net: silently drop parameters not in the provider's
# ``supported_params`` whitelist.  This prevents unknown/cross-provider
# params (e.g. Anthropic-only ``output_config`` sent to Xiaomi) from
# causing hard 400 errors.
#
# NOTE: Some providers (e.g. ``xiaomi_mimo``) have incomplete capability
# declarations in LiteLLM, which would cause ``tools`` / user-supplied
# model_kwargs to be silently discarded.  ChatLiteLLM._inject_allowed_params()
# compensates by injecting a per-call ``allowed_openai_params`` whitelist
# that takes precedence over ``drop_params`` for all explicitly-supplied keys.
litellm.drop_params = True

# Auto-handle Anthropic thinking_blocks in tool-calling multi-turn:
# if an assistant message with tool_calls is missing thinking_blocks,
# LiteLLM drops the `thinking` param for that turn instead of 400 error.
litellm.modify_params = True

# Disable telemetry for privacy
litellm.telemetry = False

# Completely disable logging of messages/prompts to protect user data
litellm.turn_off_message_logging = True

# Disable litellm's verbose logging (Provider List, etc.)
litellm.suppress_debug_info = True

# When model doesn't support function calling, litellm will try to append
# function descriptions to system prompt. Default: False.
litellm.add_function_to_prompt = False

# Model response caching configuration
litellm.cache = Cache(
    type=LiteLLMCacheType.LOCAL,
    mode=CacheMode.default_on,
    default_in_memory_ttl=3600,  # 1 hour
)
