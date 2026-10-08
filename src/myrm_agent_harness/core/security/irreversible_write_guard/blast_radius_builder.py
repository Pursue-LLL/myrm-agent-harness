"""Builder for Pre-Flight Explosion Radius (Blast Radius) Review Cards."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from .types import BlastRadiusCard, RiskLevel, WriteDomain


class BlastRadiusBuilder:
    """Constructs structured blast radius cards describing the explosion radius of write actions."""

    @staticmethod
    def build_card(
        domain: WriteDomain,
        arguments: dict[str, str],
        default_risk_level: RiskLevel = RiskLevel.HIGH,
        ttl_seconds: int = 300,
    ) -> BlastRadiusCard:
        """Build an explosion radius card from intercepted tool arguments."""
        intent_id = f"intent_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        title, summary, details, risk_level = BlastRadiusBuilder._extract_domain_profile(
            domain, arguments, default_risk_level
        )

        return BlastRadiusCard(
            intent_id=intent_id,
            domain=domain,
            title=title,
            summary=summary,
            details=details,
            risk_level=risk_level,
            created_at=now,
            expires_at=expires_at,
        )

    @staticmethod
    def _extract_domain_profile(
        domain: WriteDomain,
        arguments: dict[str, str],
        default_risk_level: RiskLevel,
    ) -> tuple[str, str, dict[str, str], RiskLevel]:
        """Extract domain-specific title, summary, details dict, and calculated risk level."""
        details: dict[str, str] = {}
        risk_level = default_risk_level

        if domain == WriteDomain.EMAIL:
            to_addr = arguments.get("to", "unknown_recipient")
            subject = arguments.get("subject", "(No Subject)")
            body = arguments.get("body", "")
            preview = body[:120] + "..." if len(body) > 120 else body

            details["to"] = to_addr
            if "cc" in arguments:
                details["cc"] = arguments["cc"]
            details["subject"] = subject
            details["body_preview"] = preview

            title = "Outgoing Email Dispatch Review"
            summary = f"Agent requests sending email to '{to_addr}' with subject '{subject}'"

        elif domain == WriteDomain.GIT_PUSH:
            remote = arguments.get("remote", "origin")
            branch = arguments.get("branch", "main")
            force = arguments.get("force", "false").lower() in ("true", "1", "yes")

            details["remote"] = remote
            details["branch"] = branch
            details["force_push"] = str(force)
            if "diff_summary" in arguments:
                details["diff_summary"] = arguments["diff_summary"]

            if force or branch in ("main", "master", "prod", "production"):
                risk_level = RiskLevel.CRITICAL

            title = "Remote Git Repository Push Review"
            summary = f"Agent requests pushing commits to remote '{remote}' branch '{branch}' (force={force})"

        elif domain == WriteDomain.PAYMENT:
            amount = arguments.get("amount", "0.00")
            currency = arguments.get("currency", "USD").upper()
            recipient = arguments.get("recipient", "external_merchant")
            desc = arguments.get("description", "Agent payment transfer")

            details["amount"] = amount
            details["currency"] = currency
            details["recipient"] = recipient
            details["description"] = desc
            risk_level = RiskLevel.CRITICAL

            title = "Financial Transaction / Payment Review"
            summary = f"Agent requests transferring {amount} {currency} to recipient '{recipient}'"

        elif domain == WriteDomain.DATABASE_WRITE:
            query = arguments.get("query", arguments.get("sql", ""))
            table = arguments.get("table", "unknown_table")
            query_preview = query[:120] + "..." if len(query) > 120 else query

            details["target_table"] = table
            details["sql_preview"] = query_preview
            if any(kw in query.upper() for kw in ("DROP", "TRUNCATE", "CASCADE")):
                risk_level = RiskLevel.CRITICAL

            title = "Mutating Database Write / DDL Review"
            summary = f"Agent requests executing mutating SQL write on table '{table}'"

        else:
            # IM_BROADCAST or fallback
            channel = arguments.get("channel", "general")
            message = arguments.get("message", "")
            msg_preview = message[:120] + "..." if len(message) > 120 else message

            details["channel"] = channel
            details["message_preview"] = msg_preview
            title = "Instant Messaging Broadcast Review"
            summary = f"Agent requests broadcasting message to channel '{channel}'"

        return title, summary, details, risk_level
