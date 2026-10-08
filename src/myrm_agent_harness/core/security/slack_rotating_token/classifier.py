"""Classifier for Slack Access and Rotating Tokens.

[INPUT]
- Raw token strings or Authorization headers, optional raw token type hints.

[OUTPUT]
- SlackTokenClassification DTO with semantic identity, lifecycle category, and rotation state.

[POS]
- Harness core security engine for OpenConnector #14c3a6c rotating token recognition.
"""

from __future__ import annotations

import re

from .types import (
    SlackTokenCategory,
    SlackTokenClassification,
    SlackTokenType,
)

BEARER_PATTERN = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)


class SlackTokenClassifier:
    """Classifies Slack access tokens, rotating tokens, and refresh tokens."""

    @staticmethod
    def strip_bearer(raw_input: str) -> tuple[str, bool]:
        """Strip optional 'Bearer ' prefix and whitespace from token input."""
        cleaned = raw_input.strip()
        match = BEARER_PATTERN.match(cleaned)
        if match:
            return match.group(1).strip(), True
        return cleaned, False

    def classify(
        self,
        token_or_auth_header: str,
        raw_token_type_hint: str | None = None,
    ) -> SlackTokenClassification:
        """Classify a Slack token into its semantic identity and lifecycle category."""
        token, is_bearer = self.strip_bearer(token_or_auth_header)

        # 1. Rotating Bot Token: xoxe.xoxb-
        if token.startswith("xoxe.xoxb-"):
            return SlackTokenClassification(
                token_type=SlackTokenType.BOT,
                category=SlackTokenCategory.ROTATING,
                is_rotating=True,
                prefix_matched="xoxe.xoxb-",
                normalized_token=token,
                is_bearer_wrapped=is_bearer,
            )

        # 2. Rotating User Token: xoxe.xoxp-
        if token.startswith("xoxe.xoxp-"):
            return SlackTokenClassification(
                token_type=SlackTokenType.USER,
                category=SlackTokenCategory.ROTATING,
                is_rotating=True,
                prefix_matched="xoxe.xoxp-",
                normalized_token=token,
                is_bearer_wrapped=is_bearer,
            )

        # 3. Rotating Refresh Token: xoxe.xoxr-
        if token.startswith("xoxe.xoxr-"):
            return SlackTokenClassification(
                token_type=SlackTokenType.REFRESH,
                category=SlackTokenCategory.REFRESH,
                is_rotating=False,
                prefix_matched="xoxe.xoxr-",
                normalized_token=token,
                is_bearer_wrapped=is_bearer,
            )

        # 4. Static Bot Token: xoxb-
        if token.startswith("xoxb-"):
            return SlackTokenClassification(
                token_type=SlackTokenType.BOT,
                category=SlackTokenCategory.STATIC,
                is_rotating=False,
                prefix_matched="xoxb-",
                normalized_token=token,
                is_bearer_wrapped=is_bearer,
            )

        # 5. Static User Token: xoxp-
        if token.startswith("xoxp-"):
            return SlackTokenClassification(
                token_type=SlackTokenType.USER,
                category=SlackTokenCategory.STATIC,
                is_rotating=False,
                prefix_matched="xoxp-",
                normalized_token=token,
                is_bearer_wrapped=is_bearer,
            )

        # 6. Static Refresh Token: xoxr-
        if token.startswith("xoxr-"):
            return SlackTokenClassification(
                token_type=SlackTokenType.REFRESH,
                category=SlackTokenCategory.REFRESH,
                is_rotating=False,
                prefix_matched="xoxr-",
                normalized_token=token,
                is_bearer_wrapped=is_bearer,
            )

        # 7. Generic Rotating Token: xoxe-
        if token.startswith("xoxe-") or token.startswith("xoxe."):
            inferred_type = SlackTokenType.UNKNOWN
            if raw_token_type_hint:
                normalized_hint = raw_token_type_hint.strip().lower()
                if normalized_hint == "bot":
                    inferred_type = SlackTokenType.BOT
                elif normalized_hint == "user":
                    inferred_type = SlackTokenType.USER
            return SlackTokenClassification(
                token_type=inferred_type,
                category=SlackTokenCategory.ROTATING,
                is_rotating=True,
                prefix_matched="xoxe",
                normalized_token=token,
                is_bearer_wrapped=is_bearer,
            )

        # 8. Fallback to raw_token_type_hint if present
        if raw_token_type_hint:
            normalized_hint = raw_token_type_hint.strip().lower()
            if normalized_hint == "bot":
                return SlackTokenClassification(
                    token_type=SlackTokenType.BOT,
                    category=SlackTokenCategory.STATIC,
                    is_rotating=False,
                    prefix_matched=None,
                    normalized_token=token,
                    is_bearer_wrapped=is_bearer,
                )
            if normalized_hint == "user":
                return SlackTokenClassification(
                    token_type=SlackTokenType.USER,
                    category=SlackTokenCategory.STATIC,
                    is_rotating=False,
                    prefix_matched=None,
                    normalized_token=token,
                    is_bearer_wrapped=is_bearer,
                )

        return SlackTokenClassification(
            token_type=SlackTokenType.UNKNOWN,
            category=SlackTokenCategory.UNKNOWN,
            is_rotating=False,
            prefix_matched=None,
            normalized_token=token,
            is_bearer_wrapped=is_bearer,
        )
