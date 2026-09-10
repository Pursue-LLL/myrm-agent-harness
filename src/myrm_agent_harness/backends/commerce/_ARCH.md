# backends/commerce/

## Overview
Dual-role commerce backend framework contracts and reference implementations.
Provides standardized protocols for Storefront (customer journey: search, product details, cart, orders, policies)
and Merchant (back-office management: performance KPIs, listing staging/apply, pricing bounds, inventory alerts).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Root | Public exports for DTOs, protocols, exceptions, and in-memory backends. | — |
| `exceptions.py` | Exceptions | Standard commerce domain exception hierarchy (`CommerceError`, `Unavailable`, `NotOffered`, etc.). | — |
| `types.py` | DTOs & States | Data transfer objects and isolated session state definitions for Storefront and Merchant roles. | — |
| `protocols.py` | Protocols | Standard abstract protocols (`StorefrontBackendProtocol`, `MerchantBackendProtocol`). | — |
| `gates.py` | Governance Gates | Options resolution (`OPTIONS_GATE`), suggestion chips, cart line/quantity caps, ID-only receipt fencing, and session mutex locking. | — |
| `guardrails.py` | Business Guardrails | Merchant guardrail gates (`GUARDRAIL_GATE`), protected field immutability, promotion depth caps, and compliant alternative generation. | — |
| `catalog_normalization.py` | Normalization & Smart Relaxation | Physical measurement unit normalization (g, kg, oz, lb, cm, in, ml) and transparent filter relaxation on zero matches. | — |
| `verticals.py` | Industry Starter Packs | Quad-vertical starter packs (Retail, Travel, Telecom, Entertainment) with pre-seeded catalogs, listings, and dual-role runtimes. | — |
| `headless_digest.py` | Commercial Digest | Headless scheduled commercial morning digest (`HeadlessDigestRunner`), KPI metrics, proactive attention items, and structured card artifacts. | — |
| `digest.py` | Digest Analytics | Commercial morning digest and proactive store health diagnostic runner (`CommercialDigestRunner`, `CommercialDigestCard`). | — |
| `checkout.py` | Checkout Handoff & AppEvents | High-level checkout modes (`APP_ROUTE`, `HOSTED_PLATFORM`, `MARKETPLACE_MULTI_SELLER`), zero-model-touch result DTOs, and turn prompt injection. | — |
| `checkout_handoff.py` | Checkout Security | Zero-model-touch payment handoff (`REDIRECT`, `IN_APP_MODAL`, `QR_CODE`), URL token stripping, and host-level card payload injection. | — |
| `app_events.py` | Asynchronous Events | Session application event queue (`AppEvent`), payment/identity completion webhook reception, and prompt context resume injection. | — |
| `memory_backend.py` | Reference Impl | Zero-dependency, testable in-memory implementations (`InMemoryStorefrontBackend`, `InMemoryMerchantBackend`). | — |

## Architecture & Design Principles

1. **Role Separation (Dual-Role Architecture)**:
   - `StorefrontBackendProtocol`: Strictly read-only for catalog/policies, session-scoped for cart mutations, customer-scoped for order tracking.
   - `MerchantBackendProtocol`: Two-phase modification workflow (`stage_listing_change` -> human/guardrail review -> `apply_staged_change`).
2. **Deterministic Governance**:
   - Out-of-stock items raise `Unavailable` with ID-only payloads to prevent prompt injection.
   - Guardrails and pricing limits are evaluated against `PricingContext` before applying live changes.
3. **Pluggable Adapters**:
   - Self-hosted e-commerce, Shopify, Magento, or ERP backends simply implement the protocols to plug seamlessly into Myrm Agent ReAct loops.
4. **Variant Options Convergence & Cart Cap Governance**:
   - Multi-option products enforce `resolve_variant_options` to prevent ambiguous parent item writes (`OPTIONS_GATE`).
   - Line and quantity limits are enforced by `check_cart_cap` with per-session async serialization (`CartSessionLock`).
   - Mutations return `CartOperationReceipt` omitting untrusted titles to prevent prompt injection.
5. **Business Guardrails & Two-Phase Staging**:
   - Price updates and promotions enforce `check_merchant_guardrails` (`GUARDRAIL_GATE`) on stage and apply.
   - Protected fields (`cost_price`, `sku`, `supplier_id`) are immutable.
   - Guardrail rejections yield actionable `compliant_alternative` payloads to steer agent re-proposals without hallucination.
6. **Quad-Vertical Starter Packs**:
   - Out-of-the-box turnkey packs for Retail, Travel, Telecom, and Entertainment.
   - Complete seed catalogs with options, real-world policies (refunds, cancellations, roaming passes), and active listings.
7. **Catalog Attribute Normalization & Smart Filter Relaxation**:
   - Converts heterogeneous physical units (grams, pounds, ounces, inches, milliliters) into canonical SI metric units before evaluation.
   - Eliminates deceptive silent filter dropping: zero matches produce explicit `RelaxationAdvice` diagnosing the bottleneck dimension and offering closest viable recommendations.
8. **Zero-Model-Touch Payment Handoff & Asynchronous AppEvent Queue**:
   - Models never receive payment URLs or credit card data (`sanitize_checkout_for_model`); URLs are injected at the host presentation layer (`inject_checkout_url_to_card`).
   - Out-of-band payment and verification achievements push `AppEvent` into `SessionAppEventQueue`, formatted into prompt context upon next turn for seamless session resumption.
9. **Scheduled Headless Commercial Digest & Proactive Anomaly Alerts**:
   - Headless single-turn diagnostic runner (`HeadlessDigestRunner`) executes scheduled store health checks (e.g., daily 08:30 AM morning audit).
   - Translates store telemetry into structured `CommerceMorningDigest` and `format_digest_card_payload` containing KPI metrics, prioritized `DigestAttentionItem` alerts with recommended actions (`plan_restock`, `restock_order`, `create_promotion`).
