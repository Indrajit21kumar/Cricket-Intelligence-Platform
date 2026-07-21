CRICKET INTELLIGENCE PLATFORM
CIP BLUEPRINT
MODULE M01
Platform Foundation
The shared skeleton every CIP service is built on — Volume 6, Module 01
Document ID: CIP-M01-FND
Version: 1.0   ·   Status: Draft
Owner: CIP Labs  ·  Prepared for: Indrajit  ·  July 2026
CONFIDENTIAL — Founding Documentation

# Document Control
Field
Value
Document ID
CIP-M01-FND
Version
1.0
Status
Draft v1.0
Owner
CIP Labs — Research & Architecture
Author
Prepared for Indrajit (Founder)
Classification
Confidential
Date
July 2026

## Version History
Version
Date
Author
Summary of Change
0.1
Jul 2026
CIP Labs
Initial outline drafted in working sessions
1.0
Jul 2026
CIP Labs
First complete professional draft of this volume

## Revision & Approval Log
Role
Name
Status
Date
Author / Chief Architect
CIP Labs
Drafted
Jul 2026
Founder / Domain Authority
Indrajit
Pending review
—
Engineering Lead
TBD
Pending
—

## Dependencies (Inputs)
- Book 2 — Reference Architecture (planes, services, contracts)
- Book 3 — Engineering Standards (coding, API, data, DevOps, DoD)
- Book 4 — CIP-STD (shared conventions)

## Feeds Into (Downstream)
- Every other module (M02–M20) is scaffolded on this foundation
- Claude Code: this is the first module to implement

# Contents
- 1. Executive Summary
- 2. Business Context
- 3. Scope & Responsibilities
- 4. Personas & Users
- 5. Functional Requirements
- 6. Non-Functional Requirements
- 7. Architecture
- 8. Database Design
- 9. API Specification
- 10. Security
- 11. Testing Strategy
- 12. Deployment & Monitoring
- 13. Future Enhancements
- 14. Claude Code Implementation Guide
- 15. Acceptance Criteria
- Appendix — Glossary

# 1. Executive Summary
Module M01, Platform Foundation, is the shared skeleton on which every other CIP service is built. It is deliberately the first module implemented, because M02–M20 all inherit its service template, configuration, data-access patterns, event-bus client, observability baseline, and multi-tenancy primitives. Building it first — and building it to standard — is what allows the rest of the platform (and AI coding agents such as Claude Code) to move quickly without re-solving cross-cutting concerns in every service.
M01 delivers no end-user cricket feature. Its 'users' are the other modules and the engineers/agents who build them. Its success is measured by how little friction later modules encounter: a new service should be scaffoldable, tenant-aware, observable, and deployable on day one.
# 2. Business Context
Book 1 established that CIP must be multi-tenant with persistent player identity and role-based access (ENG-001..003), and Book 2 defined an event-driven microservice architecture. Without a shared foundation, each of the ~20 services would re-implement authentication hooks, tenancy, logging, tracing, error handling, and configuration — inconsistently. M01 centralises these so that the Engineering Standards (Book 3) are satisfied by construction rather than by repeated effort.
Commercially, M01 has no direct revenue but is the largest single risk-reducer in the programme: it determines the velocity and consistency of every subsequent module.
# 3. Scope & Responsibilities
## 3.1 In scope
Capability
Description
Repository & project structure
The canonical layout for services, shared libraries, infra, and docs
Service template
A reference service (health, config, logging, tracing, error envelope) new services copy
Shared libraries
Tenancy context, auth middleware hooks, data-access base, event-bus client, error types
Configuration & secrets
Environment-based config loading; secrets via managed store (no secrets in code)
Multi-tenancy primitives
tenant_id propagation, row-level-security helpers, tenant context middleware
Observability baseline
Structured logging, metrics, distributed tracing keyed by correlation_id
Health & lifecycle
Liveness/readiness endpoints; graceful startup/shutdown
Base data & migrations
Shared tables (tenants, audit_log) and the migration framework
## 3.2 Out of scope
- Any cricket analysis (M05–M17), user-facing product features (M18–M20), or authentication business logic (that is M02 — M01 provides only the hooks).
# 4. Personas & Users
Persona
Need from M01
Service developer / Claude Code
Scaffold a new, standards-compliant service in minutes
Platform / DevOps engineer
Consistent config, health checks, and deploy behaviour across services
Security engineer
Uniform auth hooks, tenancy isolation, audit logging
SRE / on-call
Uniform logs, metrics, traces, and health signals for debugging
# 5. Functional Requirements
ID
Requirement (MUST unless noted)
FR-M01-01
Provide a documented, canonical repository structure for services, libraries, infra, and docs.
FR-M01-02
Provide a runnable reference service exposing /health/live and /health/ready.
FR-M01-03
Provide tenancy middleware that extracts and propagates tenant_id and correlation_id on every request/event.
FR-M01-04
Provide a data-access base enforcing tenant scoping (row-level security helper) for tenant-scoped tables.
FR-M01-05
Provide an event-bus client with idempotency-key support, publish/subscribe, and DLQ routing.
FR-M01-06
Provide a standard error envelope and error taxonomy shared across services.
FR-M01-07
Provide configuration loading from environment plus a managed secret store; MUST NOT read secrets from code.
FR-M01-08
Provide the observability baseline: structured logs, metrics, and tracing keyed by correlation_id.
FR-M01-09
Provide base schema (tenants, audit_log) and a reversible migration framework.
FR-M01-10
Provide audit-logging helper for sensitive actions (SHOULD be one call for any service).
# 6. Non-Functional Requirements
ID
Requirement
NFR-M01-01
A new service scaffolded from the template MUST pass all Book 3 CI gates out of the box.
NFR-M01-02
Health endpoints MUST respond in <100ms under normal load.
NFR-M01-03
Foundation libraries MUST be independently versioned and semver-released.
NFR-M01-04
No shared mutable global state; services remain stateless (Book 2).
NFR-M01-05
All foundation code MUST meet the coding standards (typing, lint, tests) of Book 3.
# 7. Architecture
M01 is a set of shared libraries plus a reference service and base infrastructure, not a running product service. Its components are consumed by every other module.
Component
Form
Consumed by
cip-core (lib)
Tenancy, correlation, error types, config
All services
cip-data (lib)
DB base, RLS helpers, migration runner
All stateful services
cip-events (lib)
Event-bus client, idempotency, DLQ
Pipeline services (M05–M14)
cip-observability (lib)
Logging, metrics, tracing setup
All services
reference-service
Runnable template
Copied by new services
base migrations
tenants, audit_log schema
Platform DB
# 8. Database Design
M01 owns only the shared base tables. Domain tables belong to their modules.
Table
Key columns
Notes
tenants
id (UUID), name, type, region, created_at
Root of multi-tenancy
tenant_members
id, tenant_id, user_ref, role, created_at
Role assignment within a tenant (RBAC)
audit_log
id, tenant_id, actor, action, entity, at, meta(JSONB)
Immutable record of sensitive actions
All tenant-scoped tables across the platform MUST include tenant_id and created_at/updated_at, and MUST be governed by the RLS helper from cip-data (Book 3, Ch. 4).
# 9. API Specification
Method & path
Purpose
Auth
GET /health/live
Liveness probe
None
GET /health/ready
Readiness (deps OK)
None
GET /internal/version
Build/version info
Internal
These are the only endpoints M01 defines directly; it otherwise provides the middleware and error envelope that all module APIs use.
# 10. Security
- Provides auth middleware hooks (JWT/OAuth verification points) consumed by M02; enforces that protected routes reject unauthenticated requests by default.
- Enforces tenant isolation via the RLS helper; cross-tenant access is impossible without explicit, audited elevation.
- Secrets loaded only from the managed store; secret scanning runs in CI (Book 3, Ch. 5).
- audit_log helper records sensitive actions with actor, tenant, and correlation_id.
# 11. Testing Strategy
- Unit: tenancy propagation, RLS scoping, error envelope, config loading, event idempotency — each with typical/boundary/failure fixtures (Book 3, Ch. 6).
- Integration: reference service + DB + event bus; verify a scaffolded service passes all CI gates.
- Contract: health endpoints and the shared error envelope schema.
- Security: a request without a tenant context MUST be rejected; cross-tenant read MUST be blocked (negative tests).
# 12. Deployment & Monitoring
- Packaged as containers; deployed via the standard CI/CD pipeline (Book 3, Ch. 7) to dev/staging/prod.
- Reference service exposes health endpoints wired into orchestrator liveness/readiness probes.
- Emits the observability baseline; foundation dashboards track per-service health, error rate, and trace continuity.
# 13. Future Enhancements
- Service scaffolding CLI (generate a compliant new service with one command).
- Feature-flag framework shared across services.
- Automated tenancy-isolation fuzz testing in CI.
# 14. Claude Code Implementation Guide
Implementation order for M01. Each task ends at the Book 3 Definition of Done. Later modules MUST NOT begin until FR-M01-01..09 are met.
Step
Task
Done when
1
Create repo structure + tooling (lint, format, type-check, CI skeleton)
CI runs green on an empty service
2
Build cip-core (config, tenancy context, correlation, error types)
Unit tests pass; config reads env + secret store
3
Build cip-observability (logging, metrics, tracing)
Traces thread correlation_id across a call
4
Build cip-data (DB base, RLS helper, migration runner) + base migrations (tenants, tenant_members, audit_log)
Migrations apply/rollback; RLS blocks cross-tenant reads
5
Build cip-events (publish/subscribe, idempotency, DLQ)
Duplicate delivery causes no duplicate effect
6
Assemble reference-service (health endpoints, wired middleware)
Scaffolded service passes ALL Book 3 CI gates
7
Write audit-logging helper + docs for scaffolding a new service
A new service can be created following the doc
# 15. Acceptance Criteria
ID
Acceptance criterion
AC-M01-01
A new service scaffolded from reference-service passes every Book 3 CI gate with no manual changes.
AC-M01-02
A request lacking tenant context is rejected; a cross-tenant read is blocked (negative tests pass).
AC-M01-03
correlation_id is present in logs, metrics labels, and traces across a multi-hop call.
AC-M01-04
Base migrations apply and roll back cleanly; tenants/tenant_members/audit_log exist with required columns.
AC-M01-05
The event client demonstrates idempotent consumption and DLQ routing on repeated/failed delivery.
AC-M01-06
No secret is present in source; secret scan is clean.
AC-M01-07
Health endpoints respond <100ms and drive orchestrator probes.

# Appendix — Glossary
Term
Meaning
Scaffold
Generate a new service from the reference template
RLS
Row-Level Security — DB-enforced tenant isolation
Reference service
The runnable template new services copy
correlation_id
Identifier threading one request/stroke through all hops
DLQ
Dead-letter queue for failed messages
DoD
Definition of Done (Book 3, Ch. 9)

| Field | Value |
| Document ID | CIP-M01-FND |
| Version | 1.0 |
| Status | Draft v1.0 |
| Owner | CIP Labs — Research & Architecture |
| Author | Prepared for Indrajit (Founder) |
| Classification | Confidential |
| Date | July 2026 |

| Version | Date | Author | Summary of Change |
| 0.1 | Jul 2026 | CIP Labs | Initial outline drafted in working sessions |
| 1.0 | Jul 2026 | CIP Labs | First complete professional draft of this volume |

| Role | Name | Status | Date |
| Author / Chief Architect | CIP Labs | Drafted | Jul 2026 |
| Founder / Domain Authority | Indrajit | Pending review | — |
| Engineering Lead | TBD | Pending | — |

| Capability | Description |
| Repository & project structure | The canonical layout for services, shared libraries, infra, and docs |
| Service template | A reference service (health, config, logging, tracing, error envelope) new services copy |
| Shared libraries | Tenancy context, auth middleware hooks, data-access base, event-bus client, error types |
| Configuration & secrets | Environment-based config loading; secrets via managed store (no secrets in code) |
| Multi-tenancy primitives | tenant_id propagation, row-level-security helpers, tenant context middleware |
| Observability baseline | Structured logging, metrics, distributed tracing keyed by correlation_id |
| Health & lifecycle | Liveness/readiness endpoints; graceful startup/shutdown |
| Base data & migrations | Shared tables (tenants, audit_log) and the migration framework |

| Persona | Need from M01 |
| Service developer / Claude Code | Scaffold a new, standards-compliant service in minutes |
| Platform / DevOps engineer | Consistent config, health checks, and deploy behaviour across services |
| Security engineer | Uniform auth hooks, tenancy isolation, audit logging |
| SRE / on-call | Uniform logs, metrics, traces, and health signals for debugging |

| ID | Requirement (MUST unless noted) |
| FR-M01-01 | Provide a documented, canonical repository structure for services, libraries, infra, and docs. |
| FR-M01-02 | Provide a runnable reference service exposing /health/live and /health/ready. |
| FR-M01-03 | Provide tenancy middleware that extracts and propagates tenant_id and correlation_id on every request/event. |
| FR-M01-04 | Provide a data-access base enforcing tenant scoping (row-level security helper) for tenant-scoped tables. |
| FR-M01-05 | Provide an event-bus client with idempotency-key support, publish/subscribe, and DLQ routing. |
| FR-M01-06 | Provide a standard error envelope and error taxonomy shared across services. |
| FR-M01-07 | Provide configuration loading from environment plus a managed secret store; MUST NOT read secrets from code. |
| FR-M01-08 | Provide the observability baseline: structured logs, metrics, and tracing keyed by correlation_id. |
| FR-M01-09 | Provide base schema (tenants, audit_log) and a reversible migration framework. |
| FR-M01-10 | Provide audit-logging helper for sensitive actions (SHOULD be one call for any service). |

| ID | Requirement |
| NFR-M01-01 | A new service scaffolded from the template MUST pass all Book 3 CI gates out of the box. |
| NFR-M01-02 | Health endpoints MUST respond in <100ms under normal load. |
| NFR-M01-03 | Foundation libraries MUST be independently versioned and semver-released. |
| NFR-M01-04 | No shared mutable global state; services remain stateless (Book 2). |
| NFR-M01-05 | All foundation code MUST meet the coding standards (typing, lint, tests) of Book 3. |

| Component | Form | Consumed by |
| cip-core (lib) | Tenancy, correlation, error types, config | All services |
| cip-data (lib) | DB base, RLS helpers, migration runner | All stateful services |
| cip-events (lib) | Event-bus client, idempotency, DLQ | Pipeline services (M05–M14) |
| cip-observability (lib) | Logging, metrics, tracing setup | All services |
| reference-service | Runnable template | Copied by new services |
| base migrations | tenants, audit_log schema | Platform DB |

| Table | Key columns | Notes |
| tenants | id (UUID), name, type, region, created_at | Root of multi-tenancy |
| tenant_members | id, tenant_id, user_ref, role, created_at | Role assignment within a tenant (RBAC) |
| audit_log | id, tenant_id, actor, action, entity, at, meta(JSONB) | Immutable record of sensitive actions |

| Method & path | Purpose | Auth |
| GET /health/live | Liveness probe | None |
| GET /health/ready | Readiness (deps OK) | None |
| GET /internal/version | Build/version info | Internal |

| Step | Task | Done when |
| 1 | Create repo structure + tooling (lint, format, type-check, CI skeleton) | CI runs green on an empty service |
| 2 | Build cip-core (config, tenancy context, correlation, error types) | Unit tests pass; config reads env + secret store |
| 3 | Build cip-observability (logging, metrics, tracing) | Traces thread correlation_id across a call |
| 4 | Build cip-data (DB base, RLS helper, migration runner) + base migrations (tenants, tenant_members, audit_log) | Migrations apply/rollback; RLS blocks cross-tenant reads |
| 5 | Build cip-events (publish/subscribe, idempotency, DLQ) | Duplicate delivery causes no duplicate effect |
| 6 | Assemble reference-service (health endpoints, wired middleware) | Scaffolded service passes ALL Book 3 CI gates |
| 7 | Write audit-logging helper + docs for scaffolding a new service | A new service can be created following the doc |

| ID | Acceptance criterion |
| AC-M01-01 | A new service scaffolded from reference-service passes every Book 3 CI gate with no manual changes. |
| AC-M01-02 | A request lacking tenant context is rejected; a cross-tenant read is blocked (negative tests pass). |
| AC-M01-03 | correlation_id is present in logs, metrics labels, and traces across a multi-hop call. |
| AC-M01-04 | Base migrations apply and roll back cleanly; tenants/tenant_members/audit_log exist with required columns. |
| AC-M01-05 | The event client demonstrates idempotent consumption and DLQ routing on repeated/failed delivery. |
| AC-M01-06 | No secret is present in source; secret scan is clean. |
| AC-M01-07 | Health endpoints respond <100ms and drive orchestrator probes. |

| Term | Meaning |
| Scaffold | Generate a new service from the reference template |
| RLS | Row-Level Security — DB-enforced tenant isolation |
| Reference service | The runnable template new services copy |
| correlation_id | Identifier threading one request/stroke through all hops |
| DLQ | Dead-letter queue for failed messages |
| DoD | Definition of Done (Book 3, Ch. 9) |