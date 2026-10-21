# backends/commerce/

## Overview
Dual-role commerce backend contracts. Provides standardized protocols for Storefront (customer journey: search, product details, cart, orders, policies)
and Merchant (back-office management: performance KPIs, listing staging/apply, pricing bounds, inventory alerts). Implementations are supplied by the host.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Root | Public exports for DTOs and protocols. | — |
| `types.py` | DTOs & States | Data transfer objects and isolated session state definitions for Storefront and Merchant roles. | — |
| `protocols.py` | Protocols | Standard abstract protocols (`StorefrontBackendProtocol`, `MerchantBackendProtocol`). | — |

## Architecture & Design Principles

1. **Role Separation (Dual-Role Architecture)**:
   - `StorefrontBackendProtocol`: Strictly read-only for catalog/policies, session-scoped for cart mutations, customer-scoped for order tracking.
   - `MerchantBackendProtocol`: Two-phase modification workflow (`stage_listing_change` -> human/guardrail review -> `apply_staged_change`).
2. **Pluggable Adapters**:
   - Self-hosted e-commerce, Shopify, Magento, or ERP backends simply implement the protocols to plug seamlessly into Myrm Agent ReAct loops.
