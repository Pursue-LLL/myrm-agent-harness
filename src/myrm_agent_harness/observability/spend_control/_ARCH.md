# observability/spend_control/

## Overview
Four-tier progressive spend control and soft quota intervention engine. Replaces legacy abrupt task hard-kills with an anti-disruption progressive intervention ladder:
1. **Tier 1 (70% quota)**: Real-time spend visibility & model downgrade recommendation.
2. **Tier 2 (90% quota)**: Soft spend gate with self-confirmation bypass token to allow execution to proceed smoothly.
3. **Tier 3 (100% quota)**: Seamless auto-downgrade to cost-efficient economy model (`gpt-4o-mini` / `claude-3-5-haiku`) to preserve task context and execution continuity without data loss.
4. **Tier 4 (130% quota)**: Critical pause with administrator approval ticket/link generation as an escalation mechanism rather than abrupt unrecoverable termination.
5. **Fleet Quota Deck**: Multi-dimensional attribution across agent profiles, members, and task types.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports FourTierSpendControlEngine, SpendInterventionTier, and types. | ✅ |
| `types.py` | Core | Foundation type contracts: SpendInterventionTier, InterventionAction, SpendControlConfig, SpendInterventionDecision, FleetQuotaItem. | ✅ |
| `engine.py` | Core | Thread-safe engine evaluating progressive spend tiers, soft-gate releases, auto-downgrades, and fleet attributions. | ✅ |

## Key Dependencies

- `utils/token_economics/budget_guard.py` (Protocol alignment)
- `utils/token_economics/multidim_budget.py` (Budget status alignment)
