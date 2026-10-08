# [INPUT]: AssembledContextPayload, ContextTierKind, FourTierContextConfig, FourTierContextRoutingAndSynthesisEngineSuite, JitHandle, JitRetrievalProtocol, KnowledgeSynthesisEngine, SynthesisInput, SynthesizedDirective, TriggerDomainKind, TriggeredContextRouter, TriggeredRule
# [OUTPUT]: test_four_tier_routing_suite.py
# [POS]: tests/agent/context_management/test_four_tier_routing_suite.py

"""Comprehensive test suite for FourTierContextRoutingAndSynthesisEngineSuite.

Verifies:
1. Tier 2 Triggered Context Router: Path pattern and keyword intent dynamic rule dispatch.
2. Tier 3 JIT Retrieval Protocol: Lightweight pointer catalogs and on-demand hydration.
3. Tier 4 Knowledge Synthesis Engine: Multi-source ADR/bug/doc distillation into actionable directives.
4. Top-level facade suite: End-to-end four-tier context assembly and token accounting.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.four_tier_routing import (
    AssembledContextPayload,
    ContextTierKind,
    FourTierContextConfig,
    FourTierContextRoutingAndSynthesisEngineSuite,
    JitHandle,
    JitRetrievalProtocol,
    KnowledgeSynthesisEngine,
    SynthesisInput,
    SynthesizedDirective,
    TriggerDomainKind,
    TriggeredContextRouter,
    TriggeredRule,
)


def test_triggered_context_router_path_and_intent() -> None:
    router = TriggeredContextRouter()

    # Case 1: DB path hit
    db_rules = router.route_rules(target_paths=["src/backend/db/models.py"])
    assert len(db_rules) >= 1
    assert any(r.domain == TriggerDomainKind.DATABASE for r in db_rules)
    assert any("DATABASE DISCIPLINE" in r.content for r in db_rules)

    # Case 2: API path hit
    api_rules = router.route_rules(target_paths=["src/controllers/api_endpoints.py"])
    assert len(api_rules) >= 1
    assert any(r.domain == TriggerDomainKind.API_CONTRACT for r in api_rules)

    # Case 3: Keyword intent hit (Billing & Payments)
    billing_rules = router.route_rules(intent_text="Process refund for user subscription invoice via Stripe")
    assert len(billing_rules) >= 1
    assert any(r.domain == TriggerDomainKind.PAYMENT_BILLING for r in billing_rules)

    # Case 4: Security intent hit
    sec_rules = router.route_rules(intent_text="Validate jwt token and rbac permissions")
    assert len(sec_rules) >= 1
    assert any(r.domain == TriggerDomainKind.AUTH_SECURITY for r in sec_rules)

    # Case 5: Unrelated path and intent -> zero rules triggered
    unrelated_rules = router.route_rules(target_paths=["docs/images/logo.png"], intent_text="rename image file")
    assert len(unrelated_rules) == 0


def test_jit_retrieval_protocol_hydration() -> None:
    protocol = JitRetrievalProtocol()

    handle = JitHandle(
        handle_id="jit_order_schema_v2",
        title="Order Entity Schema V2",
        summary="Detailed protobuf specification for e-commerce order contracts.",
        full_reference_pointer="schemas/proto/order_v2.proto",
    )
    protocol.register_handle(handle)

    assert protocol.total_handles() == 1
    assert protocol.hydrated_count() == 0

    # Render un-hydrated catalog (compact single line pointer)
    catalog_unhydrated = protocol.render_catalog()
    assert "[JIT Ref: jit_order_schema_v2]" in catalog_unhydrated
    assert "Un-hydrated" in catalog_unhydrated
    assert "Order Entity Schema V2" in catalog_unhydrated

    # Hydrate on demand
    hydrated = protocol.hydrate_handle("jit_order_schema_v2", content="message Order { string id = 1; int64 amount = 2; }")
    assert hydrated is not None
    assert hydrated.is_hydrated is True
    assert protocol.hydrated_count() == 1

    # Render hydrated catalog (full section expansion)
    catalog_hydrated = protocol.render_catalog()
    assert "[JIT HYDRATED REFERENCE: Order Entity Schema V2" in catalog_hydrated
    assert "message Order { string id = 1;" in catalog_hydrated

    # De-hydrate back to compact pointer
    de_hydrated = protocol.de_hydrate_handle("jit_order_schema_v2")
    assert de_hydrated is not None
    assert de_hydrated.is_hydrated is False
    assert protocol.hydrated_count() == 0


def test_knowledge_synthesis_engine_distillation() -> None:
    engine = KnowledgeSynthesisEngine()

    s_input = SynthesisInput(
        query="Refactor order status transition logic",
        adrs=[
            "ADR-042: State transitions must use StateMachine.transition() to maintain distributed locking.",
            "ADR-019: Prohibit direct SQL updates on order status field.",
        ],
        bug_histories=[
            "Bug #1042: Race condition occurred when bypassing lock during concurrent webhook delivery.",
        ],
        fragments=[
            "Order Service provides idempotent state machines for checkout flows.",
            "Use redis distributed locks with 5000ms TTL.",
        ],
    )

    directive = engine.synthesize(s_input)
    assert directive.directive_id.startswith("directive_")
    assert "Refactor order status transition logic" in directive.summary_assertion

    # Validate extracted actionable guidelines
    assert any("[ADR Constraint]: ADR-042" in g for g in directive.actionable_guidelines)
    assert any("[ADR Constraint]: ADR-019" in g for g in directive.actionable_guidelines)
    assert any("[Pattern Guidance]: Order Service provides" in g for g in directive.actionable_guidelines)

    # Validate extracted bug caution
    assert any("[Historical Bug Caution]: Bug #1042" in w for w in directive.conflict_warnings)

    # Render formatted directive
    formatted = engine.format_directive(directive)
    assert "[ENGINEERING SYNTHESIS DIRECTIVE:" in formatted
    assert "**ASSERTION**:" in formatted
    assert "**ACTIONABLE GUIDELINES**:" in formatted
    assert "**HISTORICAL PITFALLS & CONFLICTS**:" in formatted


def test_four_tier_facade_suite_assembly() -> None:
    baseline = (
        "Project: Myrm Core Engine. Invariants: zero Any types, files under 400 lines, "
        "and strict test verification."
    )
    suite = FourTierContextRoutingAndSynthesisEngineSuite.create(deterministic_baseline=baseline)

    # Register Tier 3 JIT Handle
    suite.register_jit_handle(
        JitHandle(
            handle_id="jit_cache_config",
            title="Redis Cluster Config",
            summary="Port and cluster topology for caching layer.",
            full_reference_pointer="config/redis.yaml",
        )
    )

    # Tier 4 input
    s_input = SynthesisInput(
        query="Implement caching for user queries",
        adrs=["ADR-008: All caches must declare TTL."],
        bug_histories=["Bug #304: Cache stampede on popular query keys."],
    )

    # Assemble context targeting database and performance
    payload = suite.assemble_context(
        target_paths=["src/infrastructure/database/connection.py"],
        intent_text="Optimize database query caching performance",
        synthesis_inputs=[s_input],
    )

    # Verify Tier 1 present
    assert "## [TIER 1: DETERMINISTIC BASELINE]" in payload.assembled_text
    assert "Project: Myrm Core Engine" in payload.assembled_text
    assert payload.tier_counts[ContextTierKind.DETERMINISTIC] == 1

    # Verify Tier 2 present (Database & Performance triggered)
    assert "## [TIER 2: TRIGGERED DOMAIN DISCIPLINE]" in payload.assembled_text
    assert "DATABASE DISCIPLINE" in payload.assembled_text
    assert TriggerDomainKind.DATABASE in payload.active_domains
    assert payload.tier_counts[ContextTierKind.TRIGGERED] >= 1

    # Verify Tier 3 present (JIT Reference Handle)
    assert "## [TIER 3: JIT REFERENCE HANDLES (ON-DEMAND)]" in payload.assembled_text
    assert "Redis Cluster Config" in payload.assembled_text
    assert payload.tier_counts[ContextTierKind.JIT_RETRIEVAL] == 1

    # Verify Tier 4 present (Knowledge Synthesis Directive)
    assert "## [TIER 4: MULTI-SOURCE KNOWLEDGE SYNTHESIS]" in payload.assembled_text
    assert "ADR-008: All caches must declare TTL" in payload.assembled_text
    assert payload.tier_counts[ContextTierKind.SYNTHESIS] == 1

    # Verify metrics
    assert payload.total_characters > 500
    assert payload.estimated_tokens == payload.total_characters // 4
