# delegation_billing/

## Overview
External delegation usage billing transparency and subscription entitlement divergence suite.
Inspired by Nous Portal ChatGPT federation and the critical user friction of paying API metered costs when expecting subscription reuse (Abraxas Ulysses / Fanis.TFN).
Adapts dual-shape token usage events (nested usage dict vs flat delegation data), partitions usage into subscription (zero billable API cost, estimated dollar savings calculated) vs api_key (metered direct API cost), and attributes delegation source backends.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of models and DelegationBillingTracker. | ✅ |
| `models.py` | Domain Models | Pydantic schemas for DelegationAuthMode, DelegationUsageRecord, DelegationSourceMetric, and DelegationBillingSummary. | ✅ |
| `tracker.py` | Core Tracker | DelegationBillingTracker managing dual-shape adaptation, subscription cost savings, and cross-session billing aggregation. | ✅ |
