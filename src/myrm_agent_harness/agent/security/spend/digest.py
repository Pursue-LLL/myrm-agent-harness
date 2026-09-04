"""Action digest computation and spend argument extraction.

[INPUT]
- hashlib, json (Python standard library)

[OUTPUT]
- compute_action_digest: Computes SHA-256 fingerprint binding tool, canonical args, amount, currency
- extract_spend_info: Safely inspects tool name and arguments to parse financial spend

[POS]
Pure cryptographic and parsing helpers ensuring approval binding and anti-tamper verification.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping


def canonicalize_json(data: Mapping[str, object] | list[object] | object) -> str:
    """Produce deterministic, sort-keyed JSON representation."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def compute_action_digest(
    tool_name: str,
    args: Mapping[str, object],
    amount: float,
    currency: str,
) -> str:
    """Compute cryptographic SHA-256 action digest for human approval binding.

    Covering:
    - tool_name
    - sorted, canonical arguments
    - normalized monetary amount (rounded to 4 decimal places)
    - uppercase currency symbol
    """
    canonical_args = canonicalize_json(args)
    rounded_amount = f"{amount:.4f}"
    norm_currency = currency.strip().upper()
    preimage = f"{tool_name}:{canonical_args}:{rounded_amount}:{norm_currency}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def extract_spend_info(
    tool_name: str,
    args: Mapping[str, object],
) -> tuple[float, str] | None:
    """Attempt to parse spend amount and currency from tool arguments.

    Returns:
        tuple of (amount, currency) or None if arguments do not indicate commercial spend.
    """
    if not isinstance(args, Mapping):
        return None

    raw_amount = args.get("amount") or args.get("price") or args.get("cost") or args.get("charge_amount")
    if raw_amount is None:
        return None

    try:
        parsed_amount = float(str(raw_amount).strip())
        if parsed_amount <= 0.0:
            return None
    except (ValueError, TypeError):
        return None

    raw_currency = (
        args.get("currency")
        or args.get("currency_code")
        or args.get("curr")
        or "USD"
    )
    currency = str(raw_currency).strip().upper() if raw_currency else "USD"
    return (parsed_amount, currency)
