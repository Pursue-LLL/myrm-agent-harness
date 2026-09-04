"""Spend governance and cryptographic receipt primitives for Agent Commerce.

[INPUT]
- hashlib, hmac, json: Standard cryptographic and serialization libraries

[OUTPUT]
- parse_spend_amount: Extract normalized amount and currency from tool arguments
- is_financial_or_spend_tool: Detect if tool invocation represents a financial transaction
- compute_action_digest: Cryptographic HMAC-SHA256 digest of tool + args + amount
- verify_action_digest: Timing-attack safe verification of action digest
- compute_entry_hash: Compute HMAC-chained hash for append-only tamper-evident ledger
- SpendPolicy: Data model for per-action and session spending caps
- SpendReceipt: Immutable cryptographic receipt record

[POS]
Foundational Agent Commerce governance module in core/security/.
Zero-overhead, pure deterministic algorithms ensuring YOLO-proof financial safety.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_SPEND_SALT = "myrm-agent-spend-hmac-salt"
GENESIS_PREV_HASH = "0" * 64

_SPEND_TOOL_KEYWORDS = frozenset(
    {
        "charge",
        "payment",
        "payout",
        "transfer",
        "purchase",
        "buy",
        "checkout",
        "stripe",
        "alipay",
        "wechat_pay",
        "paypal",
        "billing",
        "withdraw",
    }
)


_IRREVERSIBLE_SOCIAL_TOOLS = frozenset(
    {
        "channel_notify",
        "channel_notify_tool",
        "artifact_publish",
    }
)


def is_irreversible_social_action(tool_name: str, args: dict[str, object] | None = None) -> bool:
    """Determine if a tool call constitutes a socially irreversible external action.

    Socially irreversible actions (e.g. git push, public channel notification, package publishing)
    cannot be rolled back once dispatched into external collaborative environments.
    """
    lower_name = tool_name.lower().strip()
    if lower_name in _IRREVERSIBLE_SOCIAL_TOOLS:
        return True

    # Check for shell execution targeting git push or publish commands
    if (
        lower_name in ("shell_exec", "bash", "terminal", "code_interpreter", "bash_code_execute_tool")
        or "bash" in lower_name
        or "shell" in lower_name
    ):
        if isinstance(args, dict):
            raw_cmd = str(args.get("command") or args.get("cmd") or args.get("code") or "").strip()
            if raw_cmd:
                # Basic token matching for git push variations
                tokens = raw_cmd.lower().split()
                for idx, token in enumerate(tokens):
                    if token == "git" and idx + 1 < len(tokens) and tokens[idx + 1] == "push":
                        return True
                    if token in ("npm", "pnpm", "yarn") and idx + 1 < len(tokens) and tokens[idx + 1] == "publish":
                        return True
                    if token == "twine" and idx + 1 < len(tokens) and tokens[idx + 1] == "upload":
                        return True

    return False


def is_financial_or_spend_tool(tool_name: str, args: dict[str, object] | None = None) -> bool:
    """Determine if a tool call constitutes a financial spending action."""
    lower_name = tool_name.lower()
    for kw in _SPEND_TOOL_KEYWORDS:
        if kw in lower_name:
            return True

    if isinstance(args, dict):
        if any(k in args for k in ("amount", "total_amount", "charge_amount", "price_cents", "unit_amount")):
            return True

    return False


def parse_spend_amount(args: dict[str, object] | None) -> tuple[float | None, str | None]:
    """Extract normalized numerical amount and currency from tool arguments."""
    if not isinstance(args, dict):
        return None, None

    currency = str(args.get("currency") or "USD").upper().strip()

    # Common amount fields
    for field in (
        "amount",
        "total_amount",
        "charge_amount",
        "price_cents",
        "unit_amount",
        "amount_cents",
        "price",
        "cost",
        "value",
    ):
        if field in args and args[field] is not None:
            try:
                raw_val = float(str(args[field]))
                # Special handling for stripe-like cent representations if explicitly flagged
                if "cent" in field or (currency == "USD" and "cents" in str(args.get("unit", "")).lower()):
                    return raw_val / 100.0, currency
                return raw_val, currency
            except (ValueError, TypeError):
                continue

    return None, None


def _canonical_json(data: object) -> str:
    """Produce deterministic JSON representation for cryptographic signing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def compute_action_digest(
    tool_name: str,
    args: dict[str, object] | None,
    secret_salt: str = DEFAULT_SPEND_SALT,
) -> str:
    """Compute HMAC-SHA256 signature binding tool_name and exact arguments."""
    canonical_args = _canonical_json(args if isinstance(args, dict) else {})
    amount, currency = parse_spend_amount(args)
    payload = f"{tool_name}:{amount}:{currency}:{canonical_args}".encode("utf-8")
    return hmac.new(secret_salt.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_action_digest(
    tool_name: str,
    args: dict[str, object] | None,
    expected_digest: str,
    secret_salt: str = DEFAULT_SPEND_SALT,
) -> bool:
    """Verify action digest against tool arguments with constant-time comparison."""
    if not expected_digest:
        return False
    computed = compute_action_digest(tool_name, args, secret_salt=secret_salt)
    return hmac.compare_digest(computed, expected_digest)


def compute_entry_hash(
    prev_hash: str,
    timestamp: float,
    tool_name: str,
    amount: float | None,
    currency: str | None,
    action_digest: str,
    idempotency_key: str,
    secret_salt: str = DEFAULT_SPEND_SALT,
) -> str:
    """Compute hash for a single tamper-evident ledger entry chaining from prev_hash."""
    payload = f"{prev_hash}:{timestamp:.3f}:{tool_name}:{amount}:{currency}:{action_digest}:{idempotency_key}".encode(
        "utf-8"
    )
    return hmac.new(secret_salt.encode("utf-8"), payload, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class SpendPolicy:
    """Policy constraints for agent financial operations."""

    per_action_cap: float = 50.0
    session_cap: float = 200.0
    enabled: bool = True
    currency: str = "USD"

    def is_action_allowed(self, amount: float | None, current_session_spent: float = 0.0) -> tuple[bool, str]:
        """Check if proposed spend complies with policy caps."""
        if not self.enabled:
            return True, "Spend policy disabled"

        if amount is None or amount <= 0:
            return True, "No positive financial spend detected"

        if amount > self.per_action_cap:
            return False, f"Amount ({amount:.2f} {self.currency}) exceeds per-action cap ({self.per_action_cap:.2f} {self.currency})"

        if (current_session_spent + amount) > self.session_cap:
            return False, (
                f"Total session spend ({current_session_spent + amount:.2f} {self.currency}) "
                f"exceeds session cap ({self.session_cap:.2f} {self.currency})"
            )

        return True, "Within spend policy caps"


@dataclass(frozen=True, slots=True)
class SpendReceipt:
    """Immutable cryptographic receipt for executed financial spend."""

    entry_id: str
    session_id: str
    prev_hash: str
    entry_hash: str
    tool_name: str
    amount: float
    currency: str
    action_digest: str
    idempotency_key: str
    timestamp: float

    def verify_integrity(self, secret_salt: str = DEFAULT_SPEND_SALT) -> bool:
        """Verify receipt entry hash matches its chained inputs."""
        expected = compute_entry_hash(
            prev_hash=self.prev_hash,
            timestamp=self.timestamp,
            tool_name=self.tool_name,
            amount=self.amount,
            currency=self.currency,
            action_digest=self.action_digest,
            idempotency_key=self.idempotency_key,
            secret_salt=secret_salt,
        )
        return hmac.compare_digest(self.entry_hash, expected)
