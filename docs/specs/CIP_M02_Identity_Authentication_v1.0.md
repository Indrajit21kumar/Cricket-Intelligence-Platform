CRICKET INTELLIGENCE PLATFORM
CIP BLUEPRINT
MODULE M02
Identity & Authentication
Accounts, roles, tenancy membership, and consent — Volume 6, Module 02
Document ID: CIP-M02-IAM
Version: 1.0   ·   Status: Draft
Owner: CIP Labs  ·  Prepared for: Indrajit  ·  July 2026
CONFIDENTIAL — Founding Documentation

# Document Control
Field
Value
Document ID
CIP-M02-IAM
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
- Module M01 — Platform Foundation (tenancy, auth hooks, audit log)
- Book 2 — Reference Architecture (API gateway, RBAC)
- Book 3 — Engineering Standards (security, API, data)
- Book 0 — Manifesto §11.1 (minors' data & consent)

## Feeds Into (Downstream)
- Every product module — all access is authorised through M02
- M03 Billing, M04 Player Profile, M18 Academy/Coach

# Contents
- 1. Executive Summary
- 2. Business Context
- 3. Scope & Responsibilities
- 4. Personas & Users
- 5. Role & Permission Model
- 6. Functional Requirements
- 7. Non-Functional Requirements
- 8. Architecture
- 9. Database Design
- 10. API Specification
- 11. Consent & Minors
- 12. Security
- 13. Testing Strategy
- 14. Deployment & Monitoring
- 15. Claude Code Implementation Guide
- 16. Acceptance Criteria
- Appendix — Glossary

# 1. Executive Summary
Module M02, Identity & Authentication, is the gatekeeper of the platform. It manages accounts, verifies who a user is (authentication), determines what they may do (authorisation via RBAC), and binds users to tenants (academies, teams, or individual accounts). Because CIP serves players from age eight, M02 also owns consent — including guardian consent for minors — as a first-order responsibility, not an afterthought.
M02 is built directly on M01: it consumes the tenancy context, auth middleware hooks, and audit-logging helper the foundation provides, and adds the identity business logic on top. Every other product module delegates 'who is this and what may they do?' to M02.
# 2. Business Context
Book 1 identified that a player's technical history is lost whenever they change coach or academy, and mandated persistent player identity across organisations (ENG-002). M02 realises this by separating a person's global identity from their membership in any one tenant: a player can belong to an academy, leave it, and retain their own account and Cricket DNA. This portability is both a user benefit and part of the platform's moat.
Commercially, M02 underpins every paid tier: subscriptions (M03) attach to accounts, academy seats are memberships, and enterprise SSO is an M02 capability.
# 3. Scope & Responsibilities
## 3.1 In scope
- Registration, email/password and OAuth/SSO login, email verification, password reset.
- Session and token management (JWT issue/refresh/revoke).
- RBAC: roles, permissions, and enforcement hooks used by all modules.
- Tenancy membership: joining/leaving tenants; global player identity separate from membership.
- Consent management, including guardian consent for under-18 accounts.
- Account lifecycle: activation, suspension, deletion/export requests.
## 3.2 Out of scope
- Billing (M03), profile/Cricket DNA data (M04), academy team management UI (M18). M02 provides identity and authorisation those modules rely on.
# 4. Personas & Users
Persona
Identity need
Individual player (adult)
Self-register, own account, portable across academies
Minor player (8–17)
Guardian-consented account with restricted processing
Parent / guardian
Provide consent, oversee a minor's account
Coach
Access assigned players within a tenant
Academy / org admin
Manage members, seats, roles within their tenant
Platform admin
Cross-tenant administration (audited)
# 5. Role & Permission Model
RBAC roles are scoped to a tenant (except platform_admin). Permissions are checked on every request via the M01 auth hook.
Role
Typical permissions
player
Own videos, analyses, DNA, progress; ask AI coach
parent
View/consent for linked minor(s); no coaching edits
coach
View/analyse assigned players; create sessions; comment
academy_admin
Manage tenant members, seats, coaches; view team analytics
org_admin
As academy_admin across multiple sub-units; billing view
platform_admin
Cross-tenant admin & support (fully audited)
# 6. Functional Requirements
ID
Requirement (MUST unless noted)
FR-M02-01
Support registration via email/password with verification, and via OAuth/SSO providers.
FR-M02-02
Issue short-lived JWT access tokens with refresh tokens; support token revocation and logout-all.
FR-M02-03
Enforce RBAC on every protected endpoint through the M01 auth hook; deny by default.
FR-M02-04
Maintain global person identity distinct from tenant membership (ENG-002).
FR-M02-05
Support joining and leaving tenants without deleting the person's account or history.
FR-M02-06
Capture and enforce consent; block under-18 account activation until guardian consent is recorded.
FR-M02-07
Support account suspension and deletion/export requests (with audit).
FR-M02-08
Provide password reset and email-change flows with verification.
FR-M02-09
Record all sensitive identity actions to the M01 audit_log.
FR-M02-10
Provide an internal token-introspection endpoint for other services (SHOULD, via gateway).
# 7. Non-Functional Requirements
ID
Requirement
NFR-M02-01
Passwords hashed with a strong adaptive algorithm; never stored or logged in plaintext.
NFR-M02-02
Token verification MUST add <20ms overhead at the gateway.
NFR-M02-03
Auth endpoints MUST be rate-limited and protected against credential-stuffing.
NFR-M02-04
All PII encrypted at rest; never placed in URLs or logs (Book 3, Ch. 5).
NFR-M02-05
Availability target ≥ 99.9% — identity is on the critical path for all requests.
# 8. Architecture
M02 is a stateless service on the Application Plane, fronted by the API gateway. It issues and verifies tokens; the gateway calls M02 (or verifies signatures) to authenticate, then forwards tenant/role context downstream via the M01 middleware.
Client → API Gateway → M02 (authenticate) → issues JWT (person_id, tenant_id, role)
Subsequent requests → Gateway verifies JWT → M01 middleware injects context → target service
# 9. Database Design
Table
Key columns
Notes
persons
id (UUID), email, status, dob_band, created_at
Global identity; dob_band flags minors
credentials
id, person_id, type, hash, provider
Password hash or OAuth linkage
memberships
id, person_id, tenant_id, role, status
Person ↔ tenant with role (RBAC)
consents
id, person_id, type, granted_by, granted_at, scope
Incl. guardian consent for minors
tokens
id, person_id, kind, expires_at, revoked
Refresh/session token registry
guardianships
id, minor_person_id, guardian_person_id, verified
Links a minor to a consenting guardian
persons is a global (non-tenant) table; memberships carries the tenant_id. This separation is what makes player identity portable (FR-M02-04/05).
# 10. API Specification
Method & path
Purpose
POST /v1/auth/register
Create account (email/password)
POST /v1/auth/login
Authenticate; return access + refresh tokens
POST /v1/auth/oauth/{provider}
OAuth/SSO login
POST /v1/auth/refresh
Exchange refresh token for a new access token
POST /v1/auth/logout
Revoke current session (logout-all supported)
POST /v1/auth/password-reset
Begin password reset
POST /v1/consents
Record consent (incl. guardian consent)
POST /v1/memberships
Join a tenant (invite/accept)
DELETE /v1/memberships/{id}
Leave a tenant (account & history retained)
GET /v1/me
Current identity, roles, tenants, consent state
# 11. Consent & Minors
Per Book 0 §11.1, handling under-18 accounts is a first-order requirement. M02 enforces the following.
- An account flagged as a minor (by dob_band) MUST NOT be activated for processing until a verified guardian consent exists (FR-M02-06).
- Guardians are linked via guardianships; consent scope is explicit (e.g. analysis, storage, sharing with a coach).
- Consent can be withdrawn; withdrawal triggers the appropriate restriction/deletion workflow (with M04/data policies).
- All consent actions are audited; residency and retention follow Book 3, Ch. 4–5.
# 12. Security
- Adaptive password hashing; MFA supported (SHOULD) for admin roles.
- Short-lived access tokens; refresh rotation; revocation on logout/compromise.
- Rate limiting and lockout on auth endpoints; anomaly signals logged.
- Least-privilege internal introspection; no service can escalate its own role.
- Every sensitive action (role change, consent, deletion) written to audit_log with actor + correlation_id.
# 13. Testing Strategy
- Unit: token issue/verify/refresh/revoke; RBAC decisions per role; consent gating logic (typical/boundary/failure).
- Integration: gateway → M02 → downstream context propagation; join/leave tenant retains person + history.
- Security (negative): minor account blocked without guardian consent; cross-tenant access denied; expired/revoked token rejected; brute-force lockout.
- Contract: token and /v1/me schemas consumed by other services.
# 14. Deployment & Monitoring
- Deployed as a stateless, highly-available service (NFR-M02-05) via the standard pipeline.
- Alerts on auth error-rate spikes, token-verification latency, and lockout volume.
- Dashboards for login success rate, MFA adoption, and consent completion for minors.
# 15. Claude Code Implementation Guide
Depends on M01 being complete. Each step ends at the Book 3 Definition of Done.
Step
Task
Done when
1
Schema + migrations (persons, credentials, memberships, consents, tokens, guardianships)
Migrations apply/rollback; RLS on tenant-scoped tables
2
Registration + email verification + password login
Adult can register, verify, and log in
3
JWT issue/refresh/revoke + gateway verification
Tokens verified with <20ms overhead; logout-all works
4
RBAC roles + enforcement via M01 hook (deny by default)
Each role's permissions enforced; negative tests pass
5
Tenancy membership (join/leave) with portable identity
Leaving a tenant retains account + history
6
Consent + guardian flow for minors
Minor account blocked until verified guardian consent
7
OAuth/SSO providers
OAuth login issues equivalent tokens
8
Account lifecycle (suspend, delete/export) + audit
Requests processed and fully audited
# 16. Acceptance Criteria
ID
Acceptance criterion
AC-M02-01
An adult can register, verify email, log in, refresh, and log out (all sessions).
AC-M02-02
RBAC denies by default; each role can perform only its permitted actions (negative tests pass).
AC-M02-03
A person can leave a tenant and retain their account and history (ENG-002 verified).
AC-M02-04
A minor account cannot be activated for processing without a verified guardian consent.
AC-M02-05
Expired or revoked tokens are rejected; brute-force triggers lockout.
AC-M02-06
No password or PII appears in logs; passwords are strongly hashed.
AC-M02-07
Every role change, consent, and deletion is recorded in audit_log with actor + correlation_id.

# Appendix — Glossary
Term
Meaning
RBAC
Role-Based Access Control
JWT
JSON Web Token — signed access/identity token
Membership
A person's role within a specific tenant
Global identity
A person record independent of any tenant
Guardianship
Verified link between a minor and a consenting guardian
Consent scope
The specific processing a consent authorises
SSO / OAuth
Single sign-on / delegated authentication

| Field | Value |
| Document ID | CIP-M02-IAM |
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

| Persona | Identity need |
| Individual player (adult) | Self-register, own account, portable across academies |
| Minor player (8–17) | Guardian-consented account with restricted processing |
| Parent / guardian | Provide consent, oversee a minor's account |
| Coach | Access assigned players within a tenant |
| Academy / org admin | Manage members, seats, roles within their tenant |
| Platform admin | Cross-tenant administration (audited) |

| Role | Typical permissions |
| player | Own videos, analyses, DNA, progress; ask AI coach |
| parent | View/consent for linked minor(s); no coaching edits |
| coach | View/analyse assigned players; create sessions; comment |
| academy_admin | Manage tenant members, seats, coaches; view team analytics |
| org_admin | As academy_admin across multiple sub-units; billing view |
| platform_admin | Cross-tenant admin & support (fully audited) |

| ID | Requirement (MUST unless noted) |
| FR-M02-01 | Support registration via email/password with verification, and via OAuth/SSO providers. |
| FR-M02-02 | Issue short-lived JWT access tokens with refresh tokens; support token revocation and logout-all. |
| FR-M02-03 | Enforce RBAC on every protected endpoint through the M01 auth hook; deny by default. |
| FR-M02-04 | Maintain global person identity distinct from tenant membership (ENG-002). |
| FR-M02-05 | Support joining and leaving tenants without deleting the person's account or history. |
| FR-M02-06 | Capture and enforce consent; block under-18 account activation until guardian consent is recorded. |
| FR-M02-07 | Support account suspension and deletion/export requests (with audit). |
| FR-M02-08 | Provide password reset and email-change flows with verification. |
| FR-M02-09 | Record all sensitive identity actions to the M01 audit_log. |
| FR-M02-10 | Provide an internal token-introspection endpoint for other services (SHOULD, via gateway). |

| ID | Requirement |
| NFR-M02-01 | Passwords hashed with a strong adaptive algorithm; never stored or logged in plaintext. |
| NFR-M02-02 | Token verification MUST add <20ms overhead at the gateway. |
| NFR-M02-03 | Auth endpoints MUST be rate-limited and protected against credential-stuffing. |
| NFR-M02-04 | All PII encrypted at rest; never placed in URLs or logs (Book 3, Ch. 5). |
| NFR-M02-05 | Availability target ≥ 99.9% — identity is on the critical path for all requests. |

| Table | Key columns | Notes |
| persons | id (UUID), email, status, dob_band, created_at | Global identity; dob_band flags minors |
| credentials | id, person_id, type, hash, provider | Password hash or OAuth linkage |
| memberships | id, person_id, tenant_id, role, status | Person ↔ tenant with role (RBAC) |
| consents | id, person_id, type, granted_by, granted_at, scope | Incl. guardian consent for minors |
| tokens | id, person_id, kind, expires_at, revoked | Refresh/session token registry |
| guardianships | id, minor_person_id, guardian_person_id, verified | Links a minor to a consenting guardian |

| Method & path | Purpose |
| POST /v1/auth/register | Create account (email/password) |
| POST /v1/auth/login | Authenticate; return access + refresh tokens |
| POST /v1/auth/oauth/{provider} | OAuth/SSO login |
| POST /v1/auth/refresh | Exchange refresh token for a new access token |
| POST /v1/auth/logout | Revoke current session (logout-all supported) |
| POST /v1/auth/password-reset | Begin password reset |
| POST /v1/consents | Record consent (incl. guardian consent) |
| POST /v1/memberships | Join a tenant (invite/accept) |
| DELETE /v1/memberships/{id} | Leave a tenant (account & history retained) |
| GET /v1/me | Current identity, roles, tenants, consent state |

| Step | Task | Done when |
| 1 | Schema + migrations (persons, credentials, memberships, consents, tokens, guardianships) | Migrations apply/rollback; RLS on tenant-scoped tables |
| 2 | Registration + email verification + password login | Adult can register, verify, and log in |
| 3 | JWT issue/refresh/revoke + gateway verification | Tokens verified with <20ms overhead; logout-all works |
| 4 | RBAC roles + enforcement via M01 hook (deny by default) | Each role's permissions enforced; negative tests pass |
| 5 | Tenancy membership (join/leave) with portable identity | Leaving a tenant retains account + history |
| 6 | Consent + guardian flow for minors | Minor account blocked until verified guardian consent |
| 7 | OAuth/SSO providers | OAuth login issues equivalent tokens |
| 8 | Account lifecycle (suspend, delete/export) + audit | Requests processed and fully audited |

| ID | Acceptance criterion |
| AC-M02-01 | An adult can register, verify email, log in, refresh, and log out (all sessions). |
| AC-M02-02 | RBAC denies by default; each role can perform only its permitted actions (negative tests pass). |
| AC-M02-03 | A person can leave a tenant and retain their account and history (ENG-002 verified). |
| AC-M02-04 | A minor account cannot be activated for processing without a verified guardian consent. |
| AC-M02-05 | Expired or revoked tokens are rejected; brute-force triggers lockout. |
| AC-M02-06 | No password or PII appears in logs; passwords are strongly hashed. |
| AC-M02-07 | Every role change, consent, and deletion is recorded in audit_log with actor + correlation_id. |

| Term | Meaning |
| RBAC | Role-Based Access Control |
| JWT | JSON Web Token — signed access/identity token |
| Membership | A person's role within a specific tenant |
| Global identity | A person record independent of any tenant |
| Guardianship | Verified link between a minor and a consenting guardian |
| Consent scope | The specific processing a consent authorises |
| SSO / OAuth | Single sign-on / delegated authentication |