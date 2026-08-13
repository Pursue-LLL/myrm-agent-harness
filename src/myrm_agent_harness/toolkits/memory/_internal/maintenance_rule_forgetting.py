"""Forgetting orchestration for procedural rules (relational store).

TTL-expired rules are archived/removed directly (bypassing retention-score
thresholding), then the remaining rules flow through the standard
``ForgettingStrategy``.

[INPUT]
- memory.protocols.relational::RelationalStoreProtocol (POS: relational persistence)
- memory.types::{ProceduralMemory} (POS: memory data models)
- memory.strategies.forgetting::{ForgettingConfig, ForgettingResult, ForgettingStrategy, ttl_expired, ForgettingMode} (POS: forgetting strategy)

[OUTPUT]
- forget_procedural_rules: Apply forgetting strategy to active procedural rules

[POS]
Stateless forgetting execution for relational procedural rules.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.relational import (
        RelationalStoreProtocol,
    )
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
        ForgettingConfig,
        ForgettingResult,
        ForgettingStrategy,
    )

logger = logging.getLogger(__name__)


async def forget_procedural_rules(
    relational: RelationalStoreProtocol,
    strategy: ForgettingStrategy,
    fg_cfg: ForgettingConfig,
    result: ForgettingResult,
    namespaces: list[str] | None,
) -> None:
    """Apply forgetting strategy to ProceduralMemory stored in relational DB."""
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import ttl_expired
    from myrm_agent_harness.toolkits.memory.types import ToolRulePriority

    try:
        rules = await relational.list_rules(
            active_only=True,
            limit=fg_cfg.max_forget_per_run * 2,
            namespaces=namespaces,
        )
    except Exception as e:
        logger.warning("Forgetting: failed to fetch procedural rules: %s", e)
        return

    rules = [r for r in rules if not r.is_user_locked]

    # CRITICAL rules encode user-mandated behavior and must never be TTL-archived:
    # they flow through retention scoring with the importance floor below.
    non_critical = [r for r in rules if r.tool_rule_priority != ToolRulePriority.CRITICAL]
    expired = ttl_expired(non_critical)
    if expired:
        expired_ids = {r.id for r in expired}
        rules = [r for r in rules if r.id not in expired_ids]
        for rule in expired:
            await _apply_rule_action(
                relational,
                rule,
                reason=f"ttl_expired expected_valid_days={rule.expected_valid_days}",
                fg_cfg=fg_cfg,
                result=result,
            )

    for rule in rules:
        if rule.tool_rule_priority == ToolRulePriority.CRITICAL:
            current_importance = rule.metadata.get("importance", 0.5)
            try:
                normalized_importance = float(current_importance)
            except (TypeError, ValueError):
                normalized_importance = 0.5
            rule.metadata["importance"] = max(normalized_importance, 0.95)

    candidates = strategy.select_candidates(rules, {})
    for rule, score in candidates:
        await _apply_rule_action(
            relational,
            rule,
            reason=f"retention={score.total_score:.3f}",
            fg_cfg=fg_cfg,
            result=result,
        )


async def _apply_rule_action(
    relational: RelationalStoreProtocol,
    rule: ProceduralMemory,
    *,
    reason: str,
    fg_cfg: ForgettingConfig,
    result: ForgettingResult,
) -> None:
    """Apply the configured forgetting mode (DELETE/ARCHIVE/MARK) to one rule."""
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettingMode

    try:
        if fg_cfg.mode == ForgettingMode.DELETE:
            if await relational.delete_rule(rule.id):
                result.forgotten_count += 1
                result.forgotten_ids.append(rule.id)
        elif fg_cfg.mode == ForgettingMode.ARCHIVE:
            rule.is_active = False
            rule.metadata["archived_at"] = datetime.now(UTC).isoformat()
            rule.metadata["archive_reason"] = reason
            await relational.update_rule(rule.id, rule)
            result.archived_count += 1
            result.archived_ids.append(rule.id)
        else:
            logger.info(
                "Forgetting MARK mode: procedural rule %s (%s)",
                rule.id,
                reason,
            )
    except Exception as e:
        logger.warning("Forgetting procedural rule %s failed: %s", rule.id, e)
        result.errors.append((rule.id, str(e)))
