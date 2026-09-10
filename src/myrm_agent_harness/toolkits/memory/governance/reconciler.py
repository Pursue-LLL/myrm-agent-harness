"""Fact Reconciliation Engine.

[INPUT]
governance.models::DynamicFactItem (POS: 记忆治理领域数据模型层)
governance.models::FactStatus (POS: 记忆治理领域数据模型层)
governance.models::ReconciliationAction (POS: 记忆治理领域数据模型层)
governance.models::ReconciliationDecision (POS: 记忆治理领域数据模型层)

[OUTPUT]
ConflictResolver: 冲突仲裁协议接口
default_rule_based_resolver: 规则基线冲突消解器
FactReconciliationEngine: 事实冲突对账与生命周期管理引擎

[POS]
事实冲突对账与生命周期管理引擎。提供 ADD/UPDATE/DELETE/NOOP 四态对账消解与自适应 TTL 清扫。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from myrm_agent_harness.toolkits.memory.governance.models import (
    DynamicFactItem,
    FactStatus,
    ReconciliationAction,
    ReconciliationDecision,
)


class ConflictResolver(Protocol):
    """Protocol for resolving potential conflicts between new statement and existing fact."""

    def __call__(
        self,
        new_statement: str,
        existing_fact: DynamicFactItem,
    ) -> ReconciliationDecision | None: ...


def default_rule_based_resolver(
    new_statement: str,
    existing_fact: DynamicFactItem,
) -> ReconciliationDecision | None:
    """Heuristic rule-based resolver for detecting fact contradictions and updates."""
    clean_new = new_statement.strip().lower()
    clean_old = existing_fact.content.strip().lower()

    if clean_new == clean_old:
        return ReconciliationDecision(
            action=ReconciliationAction.NOOP,
            target_fact_id=existing_fact.fact_id,
            reason="Statement identical to existing active fact",
            confidence=1.0,
        )

    # Detect explicit revocation / cancellation
    revocation_patterns = [
        r"(?:取消|撤回|删除|放弃|不再|不要).*(?:之前|上次|关于)?\s*(.+)",
        r"(?:cancel|delete|revoke|remove|no longer)\s*(.+)",
    ]
    for pattern in revocation_patterns:
        match = re.search(pattern, clean_new)
        if match:
            target_keyword = match.group(1).strip()
            if target_keyword in clean_old or any(
                token in clean_old for token in target_keyword.split() if len(token) > 1
            ):
                return ReconciliationDecision(
                    action=ReconciliationAction.DELETE,
                    target_fact_id=existing_fact.fact_id,
                    reason=f"Explicit revocation matched keyword '{target_keyword}'",
                    confidence=0.95,
                )

    # Key-value or entity property modification pattern
    # e.g. "喜欢喝拿铁" vs "改喜欢美式了", "城市改为上海"
    update_indicators = [
        "改为",
        "改成",
        "改在",
        "变成",
        "调整为",
        "换成",
        "移到",
        "推迟到",
        "提前到",
        "重排为",
        "变更为",
        "而不是",
        "instead of",
        "changed to",
        "switched to",
        "moved to",
        "rescheduled to",
        "shifted to",
    ]
    for indicator in update_indicators:
        if indicator in clean_new:
            # Check if there is category/subject overlap via words or 2-char n-grams
            words = [w for w in re.split(r"\W+", clean_old) if len(w) > 1]
            has_word_match = any(w in clean_new for w in words)
            has_ngram_match = any(
                clean_old[i : i + 2] in clean_new
                for i in range(len(clean_old) - 1)
                if not clean_old[i : i + 2].isspace()
            )
            if has_word_match or has_ngram_match:
                return ReconciliationDecision(
                    action=ReconciliationAction.UPDATE,
                    target_fact_id=existing_fact.fact_id,
                    new_content=new_statement.strip(),
                    reason=f"Update detected via indicator '{indicator}'",
                    confidence=0.9,
                )

    # Direct negation or contradiction
    negations = ["不在", "不是", "不吃", "不喝", "不玩", "not ", "never "]
    for neg in negations:
        if neg in clean_new:
            pos_variant = clean_new.replace(neg, "")
            if pos_variant in clean_old or clean_old in pos_variant:
                return ReconciliationDecision(
                    action=ReconciliationAction.UPDATE,
                    target_fact_id=existing_fact.fact_id,
                    new_content=new_statement.strip(),
                    reason="Direct negative contradiction detected",
                    confidence=0.85,
                )
            # Negated-object heuristic: the object keyword right after the
            # negation marker (e.g. "辣" in "用户现在不吃辣了") hitting the old
            # fact indicates the old positive statement is being retracted.
            neg_idx = clean_new.find(neg)
            negated_object = clean_new[neg_idx + len(neg) : neg_idx + len(neg) + 3]
            negated_object = negated_object.rstrip("了的。 ")
            if negated_object and negated_object in clean_old:
                return ReconciliationDecision(
                    action=ReconciliationAction.UPDATE,
                    target_fact_id=existing_fact.fact_id,
                    new_content=new_statement.strip(),
                    reason=f"Negated object '{negated_object}' retracts existing fact",
                    confidence=0.8,
                )

    return None


class FactReconciliationEngine:
    """Engine responsible for dynamic fact reconciliation and TTL pruning."""

    def __init__(
        self,
        custom_resolver: ConflictResolver | None = None,
    ) -> None:
        self._resolver: ConflictResolver = (
            custom_resolver or default_rule_based_resolver
        )

    def reconcile_statement(
        self,
        new_statement: str,
        existing_facts: list[DynamicFactItem],
    ) -> ReconciliationDecision:
        """Reconcile a new statement against active dynamic facts.

        Returns one of four reconciliation decisions:
        - NOOP: Redundant information.
        - DELETE: Revocation of previous fact.
        - UPDATE: Conflict resolved by superseding an existing fact.
        - ADD: Novel fact without conflict.
        """
        active_facts = [f for f in existing_facts if f.status == FactStatus.ACTIVE]

        for fact in active_facts:
            decision = self._resolver(new_statement, fact)
            if decision is not None:
                return decision

        return ReconciliationDecision(
            action=ReconciliationAction.ADD,
            new_content=new_statement.strip(),
            reason="Novel information without conflict",
            confidence=1.0,
        )

    def apply_decision(
        self,
        decision: ReconciliationDecision,
        facts: list[DynamicFactItem],
        *,
        category: str = "general",
        valid_until: datetime | None = None,
        source_turn: str | None = None,
    ) -> list[DynamicFactItem]:
        """Apply a reconciliation decision to the fact list and return updated list."""
        result = list(facts)
        now = datetime.now(timezone.utc)

        if decision.action == ReconciliationAction.NOOP:
            return result

        if decision.action == ReconciliationAction.ADD:
            content = decision.new_content or ""
            if content:
                new_item = DynamicFactItem(
                    fact_id=str(uuid.uuid4()),
                    content=content,
                    status=FactStatus.ACTIVE,
                    category=category,
                    valid_until=valid_until,
                    confidence=decision.confidence,
                    source_turn=source_turn,
                    created_at=now,
                    updated_at=now,
                )
                result.append(new_item)
            return result

        if decision.action == ReconciliationAction.DELETE:
            for item in result:
                if item.fact_id == decision.target_fact_id:
                    item.status = FactStatus.DEPRECATED
                    item.updated_at = now
            return result

        if decision.action == ReconciliationAction.UPDATE:
            target_found = False
            for item in result:
                if item.fact_id == decision.target_fact_id:
                    item.status = FactStatus.DEPRECATED
                    item.updated_at = now
                    target_found = True
                    break

            content = decision.new_content or ""
            if content and target_found:
                new_item = DynamicFactItem(
                    fact_id=str(uuid.uuid4()),
                    content=content,
                    status=FactStatus.ACTIVE,
                    category=category,
                    valid_until=valid_until,
                    confidence=decision.confidence,
                    source_turn=source_turn,
                    created_at=now,
                    updated_at=now,
                )
                result.append(new_item)
            return result

        return result

    def purge_expired_facts(
        self,
        facts: list[DynamicFactItem],
        current_time: datetime | None = None,
    ) -> tuple[list[DynamicFactItem], list[DynamicFactItem]]:
        """Separate active facts from expired facts based on TTL.

        Returns (active_facts, expired_facts).
        """
        now = current_time or datetime.now(timezone.utc)
        active: list[DynamicFactItem] = []
        expired: list[DynamicFactItem] = []

        for fact in facts:
            if fact.status == FactStatus.ACTIVE and fact.is_expired(now):
                fact.status = FactStatus.EXPIRED
                fact.updated_at = now
                expired.append(fact)
            elif fact.status == FactStatus.ACTIVE:
                active.append(fact)

        return active, expired
