"""
[INPUT]: Raw HTTP response headers dictionary from LLM providers (OpenAI, Anthropic, DeepSeek).
[OUTPUT]: Normalized ProviderQuotaHeaderSnapshot with remaining tokens, requests, and reset clocks.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/rate_limit_governor/header_sniffer.py
"""

from datetime import datetime, timezone
import re
from typing import Dict, Optional

from .models import ProviderQuotaHeaderSnapshot


class QuotaHeaderSniffer:
    """
    Parses and standardizes provider-specific rate limit HTTP response headers
    from OpenAI, Anthropic, DeepSeek, and Qwen into normalized quota snapshots.
    """

    @staticmethod
    def _parse_time_seconds(val: Optional[str]) -> Optional[float]:
        if not val:
            return None
        val_str = str(val).strip().lower()
        try:
            return float(val_str)
        except ValueError:
            pass

        # Handle "200ms", "1.5s", "2m", "10m30s"
        match_ms = re.match(r"^(\d+(?:\.\d+)?)ms$", val_str)
        if match_ms:
            return float(match_ms.group(1)) / 1000.0

        match_s = re.match(r"^(\d+(?:\.\d+)?)s$", val_str)
        if match_s:
            return float(match_s.group(1))

        match_m = re.match(r"^(\d+(?:\.\d+)?)m$", val_str)
        if match_m:
            return float(match_m.group(1)) * 60.0

        return None

    @classmethod
    def sniff(
        cls,
        model_name: str,
        headers: Dict[str, str],
    ) -> ProviderQuotaHeaderSnapshot:
        # Normalize header keys to lowercase
        norm = {k.lower(): v for k, v in headers.items()}

        remaining_tokens: Optional[int] = None
        for key in [
            "x-ratelimit-remaining-tokens",
            "anthropic-ratelimit-tokens-remaining",
            "x-tokens-remaining",
        ]:
            if key in norm and norm[key].isdigit():
                remaining_tokens = int(norm[key])
                break

        remaining_requests: Optional[int] = None
        for key in [
            "x-ratelimit-remaining-requests",
            "anthropic-ratelimit-requests-remaining",
            "x-requests-remaining",
        ]:
            if key in norm and norm[key].isdigit():
                remaining_requests = int(norm[key])
                break

        reset_tokens: Optional[float] = None
        for key in [
            "x-ratelimit-reset-tokens",
            "anthropic-ratelimit-tokens-reset",
        ]:
            if key in norm:
                reset_tokens = cls._parse_time_seconds(norm[key])
                break

        reset_requests: Optional[float] = None
        for key in [
            "x-ratelimit-reset-requests",
            "anthropic-ratelimit-requests-reset",
        ]:
            if key in norm:
                reset_requests = cls._parse_time_seconds(norm[key])
                break

        retry_after: Optional[float] = None
        if "retry-after" in norm:
            retry_after = cls._parse_time_seconds(norm["retry-after"])

        return ProviderQuotaHeaderSnapshot(
            model_name=model_name,
            remaining_tokens=remaining_tokens,
            reset_tokens_seconds=reset_tokens,
            remaining_requests=remaining_requests,
            reset_requests_seconds=reset_requests,
            retry_after_seconds=retry_after,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )
