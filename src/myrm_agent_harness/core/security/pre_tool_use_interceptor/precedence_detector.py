"""API Key precedence detector identifying stealth per-token billing conflicts.

[INPUT]
- Active provider/subscription configuration and process environment variables.

[OUTPUT]
- Precedence check result warning of silent surcharge risks from ambient API keys.

[POS]
- Pre-flight security audit ensuring explicit billing route transparency.
"""

from __future__ import annotations

import os

from myrm_agent_harness.core.security.pre_tool_use_interceptor.types import (
    ApiKeyPrecedenceCheckResult,
)

# Common provider API keys that can silently hijack subscription routes
KNOWN_PROVIDER_ENV_KEYS: dict[str, list[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
}


class ApiKeyPrecedenceDetector:
    """Detects implicit environment API keys overriding chosen subscription billing routes."""

    @classmethod
    def detect_conflicts(
        cls,
        active_provider: str,
        is_subscription_route: bool,
        env_dict: dict[str, str] | None = None,
    ) -> ApiKeyPrecedenceCheckResult:
        """Scan environment variables to detect conflicting raw API keys.

        Args:
            active_provider: Name of selected provider (e.g., 'anthropic', 'openai').
            is_subscription_route: True if user selected a flat-rate subscription (Pro/Max/Team).
            env_dict: Optional environment dictionary override (defaults to os.environ).

        Returns:
            ApiKeyPrecedenceCheckResult with conflict warnings if ambient keys exist.
        """
        env = env_dict if env_dict is not None else dict(os.environ)
        provider_normalized = active_provider.lower().strip()

        # Find matching keys for the target provider
        relevant_keys = KNOWN_PROVIDER_ENV_KEYS.get(provider_normalized, [])
        detected_keys = [k for k in relevant_keys if k in env and env[k].strip()]

        if is_subscription_route and detected_keys:
            keys_str = ", ".join(detected_keys)
            return ApiKeyPrecedenceCheckResult(
                has_conflict=True,
                detected_env_vars=detected_keys,
                active_provider=active_provider,
                warning_message=(
                    f"Ambient environment variable(s) [{keys_str}] detected while using "
                    f"subscription route for '{active_provider}'. CLI tools or SDKs may prioritize "
                    f"the ambient API key and silently incur unexpected pay-as-you-go surcharges."
                ),
                recommended_action=(
                    f"Unset [{keys_str}] in your shell environment, or configure explicit billing "
                    f"precedence in Settings."
                ),
            )

        return ApiKeyPrecedenceCheckResult(
            has_conflict=False,
            detected_env_vars=detected_keys,
            active_provider=active_provider,
        )
