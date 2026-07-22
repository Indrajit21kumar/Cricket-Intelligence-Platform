# Module M03 — Subscription & Billing

**CIP Blueprint · Volume 6 (Module Specifications)**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M03-BIL |
| Version | 1.0 |
| Status | Draft v1.0 |
| Owner | CIP Labs — Product & Platform |
| Classification | Confidential |
| Date | July 2026 |

**Version History**

| Version | Date | Author | Summary |
|---|---|---|---|
| 0.1 | Jul 2026 | CIP Labs | Outline |
| 1.0 | Jul 2026 | CIP Labs | First complete draft |

**Dependencies (Inputs)**

- Module M01 — Platform Foundation (tenancy, config, audit log, event client)
- Module M02 — Identity & Authentication (persons, memberships, tenants, RBAC)
- Book 2 — Reference Architecture (Application Plane; Partner API; ENG-004)
- Book 3 — Engineering Standards (API, data, security, DoD)
- Book 0 — Manifesto §9 (plan/tier model)

**Feeds Into (Downstream)**

- All feature modules — entitlements/quotas gate access to paid capabilities
- M18 Academy/Coach (seat management); M20 Admin & Analytics (revenue reporting)

---

## Contents

1. Executive Summary
2. Business Context
3. Scope & Responsibilities
4. Personas & Users
5. Plans & Entitlement Model
6. Functional Requirements
7. Non-Functional Requirements
8. Architecture
9. Database Design
10. API Specification
11. Security
12. Testing Strategy
13. Deployment & Monitoring
14. Future Enhancements
15. Claude Code Implementation Guide
16. Acceptance Criteria
17. Appendix — Glossary

---

## 1. Executive Summary

Module M03, Subscription & Billing, is the commercial engine of the platform. It defines the subscription plans, tracks metered usage (principally the number of video analyses consumed), enforces entitlements so every other module can gate paid features, and manages the billing lifecycle — subscribe, upgrade, downgrade, cancel, invoice, prorate, and recover failed payments (dunning).

M03 owns *what a customer is entitled to*; it does not itself perform cricket analysis. It exposes a fast **entitlement check** that feature modules call before doing paid work (for example, M05 Video Intelligence asks "does this account have an analysis quota remaining?"). Actual money movement is delegated to an external payment provider through a thin, swappable integration — CIP records intent and reconciles provider events; it never stores raw card data.

## 2. Business Context

Book 0 §9 defines four commercial tiers (Starter/Free, Pro, Academy, Enterprise). Book 1 established that CIP is a multi-sided platform serving individuals and institutions, so billing must handle both self-serve individual subscriptions and seat-based academy/enterprise contracts. M03 turns the platform's capabilities into revenue while keeping entitlement logic in one authoritative place rather than scattered across feature modules.

Because subscriptions attach to identities and tenants (M02), and because feature access must be enforced consistently, M03 is a prerequisite for monetising any feature module.

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Plan catalogue | Definition of plans, prices, and the entitlements each grants |
| Subscription lifecycle | Subscribe, upgrade, downgrade, cancel, renew, trial |
| Usage metering | Record consumption of metered units (e.g. analyses/month) |
| Entitlement service | Fast check other modules call to authorise paid actions |
| Invoicing & payments | Integrate a payment provider via webhooks; record invoices |
| Proration & dunning | Fair mid-cycle changes; retry/notify on failed payment |
| Seats | Academy/enterprise multi-player seat allocation |
| Billing audit | Immutable record of billing events |

### 3.2 Out of scope

- Storing raw payment credentials or executing card transactions directly (delegated to the payment provider).
- Identity/roles (M02), academy team UI (M18), and the analytics warehouse (M20 consumes M03 events).

## 4. Personas & Users

| Persona | Need from M03 |
|---|---|
| Individual player | Subscribe to Pro; see usage and invoices; upgrade/cancel |
| Parent/guardian | Pay for a minor's plan; manage the subscription |
| Academy admin | Buy/allocate seats; single invoice for many players |
| Org/enterprise admin | Contract terms, seat pools, Partner API entitlement |
| Platform admin | Manage plans, issue credits, view revenue (audited) |
| Other modules | Call the entitlement API before paid work |

## 5. Plans & Entitlement Model

Plans grant **entitlements** (feature flags + quotas). Feature modules never hard-code plan names; they check entitlements. This keeps pricing changes from touching feature code.

| Plan | Indicative entitlements |
|---|---|
| Starter / Free | Limited analyses/month; basic technique score; no AI coach |
| Pro | Unlimited (fair-use) analyses; AI Coach; Cricket DNA; progress tracking; legend comparison |
| Academy | Multi-player seats; coach dashboard; team reports; per-seat quotas |
| Enterprise | Partner/Performance API; white-label; custom quotas; SSO |

Entitlement examples (stable keys consumed by other modules): `analysis.quota_monthly`, `feature.ai_coach`, `feature.legend_comparison`, `feature.partner_api`, `seats.max`.

## 6. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M03-01 | Maintain a versioned plan catalogue mapping plans → entitlements (flags + quotas). |
| FR-M03-02 | Support subscribe, upgrade, downgrade, cancel, renew, and trial for an account or tenant. |
| FR-M03-03 | Record metered usage events (e.g. `analysis.consumed`) idempotently against a billing period. |
| FR-M03-04 | Expose a low-latency entitlement check: `is X allowed / quota remaining?` for a subject. |
| FR-M03-05 | Integrate a payment provider via webhooks; record invoices and payment status; never store raw card data. |
| FR-M03-06 | Prorate charges/credits on mid-cycle plan changes. |
| FR-M03-07 | Run dunning on failed payment: retry schedule + notifications (via M19); suspend on final failure. |
| FR-M03-08 | Support seat-based plans: allocate/deallocate seats to tenant members (M02 memberships). |
| FR-M03-09 | Emit billing events (`subscription.changed`, `invoice.paid`, `usage.recorded`) to the event bus for M20. |
| FR-M03-10 | Record all billing actions to the M01 `audit_log`. |
| FR-M03-11 | SHOULD support promo codes / credits issued by platform_admin. |

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-M03-01 | Entitlement check MUST return in <30ms (cached) to avoid adding latency to feature requests. |
| NFR-M03-02 | Usage metering MUST be exactly-once per unit within a period (idempotency keys). |
| NFR-M03-03 | No raw PAN/card data stored; PCI scope minimised by using the provider's tokenisation. |
| NFR-M03-04 | Billing records MUST be immutable and reconcilable against provider records. |
| NFR-M03-05 | Availability ≥ 99.9%; entitlement checks degrade to last-known-good on provider outage. |

## 8. Architecture

M03 is a stateless service on the **Application Plane** (Book 2, Ch. 2). It owns its datastore, consumes M02 for subject identity, calls an external payment provider through an adapter, and publishes billing events consumed by M20. The entitlement check is served from a fast cache (Redis) backed by the datastore.

```
Feature module → M03 /entitlements/check (cached) → allow / deny (+ remaining quota)
Client → M03 subscribe → Payment Provider (adapter) → webhook → M03 records invoice → event: subscription.changed
Feature module → event: analysis.consumed → M03 meters usage against period
```

Boundary rule (ENG-004): entitlement logic lives only in M03; feature modules ask, they do not compute entitlements.

## 9. Database Design

| Table | Key columns | Notes |
|---|---|---|
| plans | id, code, name, version, active | Plan catalogue (versioned) |
| plan_entitlements | id, plan_id, key, value | Flags + quota values per plan |
| subscriptions | id, tenant_id, subject_ref, plan_id, status, period_start, period_end | Account/tenant subscription |
| usage_records | id, subscription_id, meter_key, qty, period, idempotency_key | Metered consumption |
| invoices | id, subscription_id, amount, currency, status, provider_ref, issued_at | Provider-reconciled |
| seats | id, tenant_id, subscription_id, member_ref, status | Seat allocation |
| billing_audit | id, tenant_id, actor, action, entity, at, meta | Immutable billing log |

All tenant-scoped tables carry `tenant_id` + `created_at/updated_at` and are governed by the M01 row-level-security helper (Book 3, Ch. 4). `usage_records.idempotency_key` enforces NFR-M03-02.

## 10. API Specification

| Method & path | Purpose |
|---|---|
| GET /v1/plans | List available plans + entitlements |
| POST /v1/subscriptions | Subscribe an account/tenant to a plan |
| PATCH /v1/subscriptions/{id} | Upgrade/downgrade/cancel (prorated) |
| GET /v1/subscriptions/{id} | Current status, period, entitlements |
| POST /v1/entitlements/check | Internal: `{subject, key}` → `{allowed, remaining}` |
| POST /v1/usage | Internal: record a metered usage event (idempotent) |
| POST /v1/seats | Allocate a seat to a member |
| DELETE /v1/seats/{id} | Deallocate a seat |
| POST /v1/webhooks/payments | Provider webhook (signed) → invoice/payment updates |
| GET /v1/invoices | List invoices for the subject |

Standards: versioned paths, standard error envelope, idempotency keys on POSTs, signed webhooks (Book 3, Ch. 3).

## 11. Security

- Webhook endpoints MUST verify provider signatures; reject unsigned/replayed events.
- No raw card data enters CIP; only provider tokens/refs are stored (NFR-M03-03).
- Entitlement and billing changes are RBAC-gated (M02) and audited (`billing_audit` + M01 `audit_log`).
- PII in invoices is encrypted at rest; never placed in URLs/logs (Book 3, Ch. 5).
- Financial actions are provider-side; CIP records intent and reconciles — it does not move money directly.

## 12. Testing Strategy

- **Unit:** proration math, entitlement resolution per plan, usage idempotency, dunning state machine (typical/boundary/failure fixtures — Book 3, Ch. 6).
- **Integration:** subscribe → provider webhook → invoice recorded → `subscription.changed` emitted; usage event → quota decremented.
- **Contract:** entitlement-check and usage schemas consumed by feature modules; webhook payload schema.
- **Security (negative):** unsigned/replayed webhook rejected; quota-exceeded action denied; cross-tenant subscription access blocked.

## 13. Deployment & Monitoring

- Stateless HA service via the standard pipeline (Book 3, Ch. 7); entitlement cache warmed on deploy.
- Alerts: failed-payment rate, webhook processing lag, entitlement-check latency, dunning backlog.
- Dashboards: MRR/active subscriptions, conversion, usage vs quota distribution, involuntary churn.

## 14. Future Enhancements

- Regional pricing and tax handling; multi-currency.
- Usage-based (per-analysis) billing option for enterprise.
- Self-serve plan experiments (A/B pricing) behind the entitlement layer.

## 15. Claude Code Implementation Guide

Depends on M01 and M02 being complete. Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | Schema + migrations (plans, plan_entitlements, subscriptions, usage_records, invoices, seats, billing_audit) | Migrations apply/rollback; RLS on tenant-scoped tables |
| 2 | Plan catalogue + entitlement resolution | Given a plan, entitlements (flags + quotas) resolve correctly |
| 3 | Entitlement-check API + cache | Check returns <30ms; quota-remaining correct; degrades to last-known-good |
| 4 | Usage metering (idempotent) | Duplicate usage events counted once per period |
| 5 | Subscription lifecycle (subscribe/upgrade/downgrade/cancel) + proration | Mid-cycle change prorates correctly |
| 6 | Payment provider adapter + signed webhooks + invoices | Webhook updates invoice/payment; signatures verified |
| 7 | Dunning state machine + M19 notifications + suspend-on-final-failure | Failed payment retries, notifies, then suspends |
| 8 | Seats for academy/enterprise + billing events to M20 + audit | Seats allocate/deallocate; events emitted; actions audited |

## 16. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M03-01 | A subject can subscribe, upgrade (prorated), and cancel; status and entitlements update correctly. |
| AC-M03-02 | Entitlement check returns allow/deny + remaining quota in <30ms and degrades gracefully on provider outage. |
| AC-M03-03 | Metered usage is exactly-once per period; a duplicate `analysis.consumed` is not double-counted. |
| AC-M03-04 | A provider webhook records the correct invoice/payment status; unsigned/replayed webhooks are rejected. |
| AC-M03-05 | Failed payment triggers the dunning schedule, notifies via M19, and suspends on final failure. |
| AC-M03-06 | Academy seats allocate/deallocate against M02 memberships and respect `seats.max`. |
| AC-M03-07 | No raw card data is stored; all billing actions are audited with actor + correlation_id. |

## 17. Appendix — Glossary

| Term | Meaning |
|---|---|
| Entitlement | A feature flag or quota granted by a plan |
| Metered usage | Consumption of a billable unit (e.g. an analysis) |
| Proration | Fair mid-cycle charge/credit on plan change |
| Dunning | The retry + notify process on failed payment |
| Seat | A per-member allocation within a tenant plan |
| PAN | Primary Account Number (card number) — never stored |
| MRR | Monthly Recurring Revenue |
