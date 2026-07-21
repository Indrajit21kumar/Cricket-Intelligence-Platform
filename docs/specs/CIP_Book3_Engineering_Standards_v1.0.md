CRICKET INTELLIGENCE PLATFORM
CIP BLUEPRINT
BOOK 3
Engineering Standards
The binding rules for how CIP code, APIs, data, and models are built
Document ID: CIP-B3-STD
Version: 1.0   ·   Status: Draft
Owner: CIP Labs  ·  Prepared for: Indrajit  ·  July 2026
CONFIDENTIAL — Founding Documentation

# Document Control
Field
Value
Document ID
CIP-B3-STD
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
- Book 0 — Manifesto (principles, Trust Doctrine)
- Book 1 — GCIR (requirements register)
- Book 2 — Reference Architecture (services, contracts, planes)

## Feeds Into (Downstream)
- All module specifications (Volume 6+): every module's implementation must conform
- Claude Code implementation guides (per-module Definition of Done)

# Contents
- Chapter 1 — Purpose & How These Standards Are Enforced
- Chapter 2 — Coding Standards
- Chapter 3 — API Design Standards
- Chapter 4 — Data & Schema Standards
- Chapter 5 — Security & Privacy Standards
- Chapter 6 — Testing & AI Validation Standards
- Chapter 7 — DevOps, CI/CD & Environments
- Chapter 8 — Observability & Reliability Standards
- Chapter 9 — Documentation & Definition of Done
- Appendix A — Standards Compliance Checklist
- Appendix B — Traceability
- Appendix C — Glossary & Acronyms

# Chapter 1 — Purpose & How These Standards Are Enforced
Document ID: STD-CH-001
Books 1 and 2 defined what to build and how it fits together. This volume defines the quality bar every unit of work must clear. These standards are binding: a module is not 'done' until it conforms (Chapter 9). They exist so that many contributors — human engineers and AI coding agents such as Claude Code — produce consistent, reviewable, trustworthy software.
## 1.1 Normative language
MUST = mandatory for release. SHOULD = strong default; deviation requires a documented justification in the module spec. MAY = discretionary. These follow RFC 2119 semantics, consistent with the module specs.
## 1.2 Enforcement mechanisms
Standard area
Enforced by
Coding
Linters, formatters, code review, CI gates
API
Contract tests, schema linting, versioning checks
Data
Migration review, schema registry compatibility checks
Security
SAST/dependency scans, security review, secrets scanning
Testing / AI
Coverage gates, golden-dataset validation gates
Docs / DoD
PR checklist, module acceptance criteria
### Research Findings
- A single, enforced standard is what lets AI agents contribute safely at scale.
### Business Implications
- Consistency lowers onboarding cost and de-risks outsourced/AI-assisted work.
### Engineering Implications
- Standards are enforced by automation in CI, not by memory.
### AI Implications
- Claude Code is given these standards as context so generated code conforms by construction.
### Future Research Questions
- Which deviations are pre-approved vs require sign-off?
### Traceability
- Governs every module in Volume 6+.

# Chapter 2 — Coding Standards
Document ID: STD-CH-002
## 2.1 Languages & frameworks
Layer
Standard
Notes
Backend / services
Python (FastAPI)
One primary backend language; async where I/O-bound
ML / vision
Python (PyTorch, OpenCV)
Shared language with backend simplifies the team
Web frontend
TypeScript + Next.js/React + Tailwind
Type-safe UI; SSR where beneficial
Mobile
React Native (TypeScript)
One codebase for iOS/Android capture app
## 2.2 Rules (MUST)
- MUST pass the repository linter and formatter (e.g. Ruff/Black for Python, ESLint/Prettier for TS) with zero errors before merge.
- MUST use static typing (Python type hints; TypeScript strict mode); public functions MUST be typed.
- MUST NOT hard-code secrets, credentials, or environment-specific values; use configuration/secret management.
- MUST handle and log errors explicitly; no silent failures (aligns with pipeline DLQ policy).
- SHOULD keep functions small and single-purpose; SHOULD favour pure functions in analytical code for testability.
## 2.3 Repository & versioning
- Trunk-based or short-lived feature branches; every change via reviewed pull request.
- Conventional commit messages; semantic versioning for released services and libraries.
- No direct commits to main; CI must pass to merge.
### Research Findings
- A single backend/ML language (Python) plus TS front end minimises context-switching.
### Business Implications
- Fewer languages = a smaller, more fungible team.
### Engineering Implications
- Typing + linting + review + CI are the four coding gates.
- Pure analytical functions are a testing requirement, not just a preference.
### AI Implications
- Typed, linted, pure functions are exactly what AI agents generate and test most reliably.
### Future Research Questions
- Monorepo vs polyrepo for the service set?
### Traceability
- Enforces P1 (quality over speed); feeds every module's implementation.

# Chapter 3 — API Design Standards
Document ID: STD-CH-003
## 3.1 External REST APIs
- MUST be versioned in the path (/v1/...); breaking changes require a new version.
- MUST use a consistent error envelope: { error: { code, message, details, request_id } }.
- MUST accept an Idempotency-Key header on all mutating (POST/PUT/PATCH) requests.
- MUST paginate list endpoints with cursors; MUST expose rate-limit headers.
- MUST authenticate via the gateway (JWT/OAuth); no service is publicly reachable un-gated.
## 3.2 Internal service APIs
- MAY use gRPC where latency-sensitive; otherwise REST/JSON.
- MUST publish an OpenAPI (or protobuf) contract; contract tests MUST run in CI.
## 3.3 Event contracts
- Every event MUST carry correlation_id, schema_version, produced_at, and quality/provenance fields (Book 2, Ch. 4).
- Schema changes MUST be backward-compatible or introduce a new versioned topic; the schema registry enforces this.
## 3.4 Standard error codes
HTTP
Meaning in CIP
400
Malformed request
401 / 403
Unauthenticated / unauthorised (RBAC)
409
Idempotency or state conflict
422
Valid request, unprocessable (e.g. clip fails quality gate)
202
Accepted; analysis running / provisional result
429
Rate limit exceeded
### Research Findings
- Uniform versioning, errors, idempotency, and pagination make every API predictable.
### Business Implications
- A clean, stable Partner API is directly monetisable (Enterprise tier).
### Engineering Implications
- Contract tests in CI prevent breaking consumers.
- 422/202 encode the graceful-degradation behaviour of the pipeline.
### AI Implications
- OpenAPI contracts are ideal inputs for AI-generated clients and tests.
### Future Research Questions
- Webhook signing scheme for report.ready partner callbacks?
### Traceability
- Implements Book 2, Ch. 7; feeds Modules M02, M05, M14, M15.

# Chapter 4 — Data & Schema Standards
Document ID: STD-CH-004
## 4.1 Relational standards
- MUST use UUID primary keys; MUST include created_at/updated_at on every table.
- MUST include tenant_id on all tenant-scoped tables and enforce row-level security (ENG-001).
- MUST express schema changes as reviewed, reversible migrations; no manual production DDL.
- SHOULD index foreign keys and common query predicates; SHOULD use JSONB for flexible metric payloads with a GIN index.
## 4.2 Metric storage & provenance (TRUST-001)
Every stored metric MUST record its provenance label (measured / estimated / modelled) and, where estimated or modelled, a confidence value. A metric without a provenance label is a schema violation.
## 4.3 Object storage
- MUST namespace objects by tenant and player; MUST apply lifecycle rules to tier ageing video to cold storage.
- MUST store analysis artefacts (pose/bat/ball/report) with the correlation_id for traceability.
## 4.4 Data lifecycle & minors
- MUST support consent-governed retention, export, and deletion, including guardian consent for minors (Book 0 §11.1).
- MUST support data-residency placement where a market requires it.
### Research Findings
- Provenance-labelled metrics are a schema-level requirement, not a UI nicety.
### Business Implications
- Retention/export/deletion controls are compliance prerequisites for global sale.
### Engineering Implications
- tenant_id + RLS everywhere; migrations only.
- correlation_id links every artefact back to its source clip.
### AI Implications
- The labelled metric store is also the curated substrate for model training.
### Future Research Questions
- Retention windows per data class and per jurisdiction?
### Traceability
- Implements ENG-001, ENG-002, TRUST-001; Book 0 §11.1.

# Chapter 5 — Security & Privacy Standards
Document ID: STD-CH-005
## 5.1 Authentication & authorisation
- MUST authenticate with JWT/OAuth; tokens short-lived with refresh; MUST enforce RBAC on every endpoint (ENG-003).
- MUST apply least privilege to service-to-service credentials; secrets in a managed secret store, never in code or images.
## 5.2 Data protection
- MUST encrypt data in transit (TLS) and at rest; MUST NOT place personal data in URLs/query strings or logs.
- MUST audit-log sensitive actions (access to minors' data, exports, role changes).
## 5.3 Privacy & compliance
- MUST implement consent flows (incl. guardian consent for under-18s) and honour deletion/export requests.
- MUST be able to satisfy GDPR-style and COPPA-style obligations per market; data residency configurable.
## 5.4 Responsible AI
- MUST label outputs by provenance (TRUST-001) and MUST NOT present estimates as measurements.
- MUST use only derived legend benchmarks; MUST NOT claim endorsement or use unlicensed proprietary datasets (TRUST-002).
- MUST clearly separate movement-risk indicators from medical diagnosis (Book 0 §11.3).
### Research Findings
- Security and privacy are cross-cutting MUSTs, verified in CI and review, not optional.
### Business Implications
- Compliance-by-design is a precondition for academies, schools, and boards.
### Engineering Implications
- RBAC on every endpoint; least-privilege service identities; secrets managed.
- Audit logging of sensitive actions is mandatory.
### AI Implications
- Guardrails (provenance, legend-benchmark, non-medical) are enforced server-side.
### Future Research Questions
- Which markets first, and what are their specific children's-data rules?
### Traceability
- Implements ENG-003, TRUST-001/002; Book 0 §11; Book 2 Ch. 9.

# Chapter 6 — Testing & AI Validation Standards
Document ID: STD-CH-006
## 6.1 The test pyramid
Level
Requirement
Unit
MUST cover business logic and every analytical formula against hand-computed fixtures (min 3 cases each: typical, boundary, degenerate)
Integration
MUST verify service + datastore + event contracts
Contract
MUST verify API/event schemas between producer and consumer
End-to-end
SHOULD verify the full upload→report pipeline on sample clips
AI evaluation
MUST validate models against a versioned golden dataset with defined tolerances
## 6.2 AI validation (release-gating)
Model or pipeline changes MUST NOT ship if they regress mean error beyond the tolerance bands defined per metric (e.g. angular ±5°, timing ±2 frames, positional ±3cm, velocity ±10%). Validation runs on a held-out golden dataset with mocap-derived ground truth. This gate is the objective bar referenced throughout the blueprint.
## 6.3 Coverage & CI
- MUST meet the repository coverage threshold on changed code; CI MUST block merges that fail tests or gates.
- Regression snapshots of representative outputs MUST be maintained for analytical/model services.
### Research Findings
- AI validation is a first-class test level, gating releases like any other test.
### Business Implications
- Objective accuracy gates are what let CIP make honest, defensible accuracy claims.
### Engineering Implications
- Every formula has fixtures; every model change faces the golden dataset.
### AI Implications
- Golden-dataset tolerances are the contract between ambition and honesty (Trust Doctrine).
### Future Research Questions
- Who owns and curates the golden dataset, and how is it grown?
### Traceability
- Implements ENG-007; SR-003 (variability); Book 0 §8.

# Chapter 7 — DevOps, CI/CD & Environments
Document ID: STD-CH-007
- MUST provision infrastructure as code (e.g. Terraform); no manual production changes.
- MUST maintain isolated dev / staging / production environments.
- CI pipeline MUST run: lint → type-check → unit → integration → contract → security scan → build; all green to merge.
- CD MUST support canary rollout and instant rollback; model deploys MUST pass the AI validation gate first (ENG-007).
- GPU serving pools MUST autoscale on queue depth and scale to zero when idle; training SHOULD use spot/preemptible instances.
### Research Findings
- A uniform CI/CD gate sequence applies to code and models alike.
### Business Implications
- Scale-to-zero GPU keeps burn aligned with the feasibility cost model.
### Engineering Implications
- IaC + reproducible environments + canary/rollback are mandatory.
### AI Implications
- No model reaches production without passing validation — enforced in CD.
### Future Research Questions
- Managed Kubernetes vs serverless GPU at current scale?
### Traceability
- Implements Book 2 Ch. 8–9; ENG-007.

# Chapter 8 — Observability & Reliability Standards
Document ID: STD-CH-008
- MUST emit structured logs, metrics, and distributed traces keyed by correlation_id across the pipeline.
- MUST define SLOs per stage (latency, error rate) and alert on breaches and on DLQ backlog.
- MUST define backup schedules and RPO/RTO targets for every datastore.
- SHOULD publish model-performance dashboards (drift, confidence distributions) for each deployed model.
### Research Findings
- correlation_id-based tracing makes the async pipeline debuggable end to end.
### Business Implications
- SLOs become contractual commitments for Academy/Enterprise tiers.
### Engineering Implications
- DLQ backlog and stage latency are primary alerts.
- Every datastore has an RPO/RTO.
### AI Implications
- Drift and confidence dashboards are standing model-health signals.
### Future Research Questions
- Which SLOs are externally committed vs internal targets?
### Traceability
- Implements Book 2 Ch. 9.

# Chapter 9 — Documentation & Definition of Done
Document ID: STD-CH-009
A feature or module is complete only when all of the following are satisfied. This Definition of Done is the acceptance gate cited by every module specification and every Claude Code task.
#
Definition-of-Done criterion
1
Functional implementation meeting the module's acceptance criteria
2
Unit tests (incl. formula fixtures) passing at required coverage
3
Integration + contract tests passing
4
AI validation passed against the golden dataset (for model work)
5
API/event contracts published and versioned
6
Security review + scans clean; provenance labels present (TRUST-001)
7
Performance within the stage's latency/throughput budget
8
Observability wired (logs, metrics, traces, alerts)
9
User + API documentation updated
10
Accessibility review for user-facing surfaces (WCAG 2.1 AA)
### Research Findings
- A single, explicit Definition of Done keeps quality uniform across contributors and AI agents.
### Business Implications
- Predictable 'done' improves delivery forecasting and trust.
### Engineering Implications
- No merge without all ten criteria for the relevant work type.
### AI Implications
- Claude Code tasks reference this list as their acceptance contract.
### Future Research Questions
- Which criteria are waivable for internal-only services?
### Traceability
- Governs acceptance for every module in Volume 6+.

# Appendix A — Standards Compliance Checklist
Area
Gate
Blocking?
Coding
Lint + type-check + review
Yes
API
Contract tests + version check
Yes
Data
Migration review + schema compatibility
Yes
Security
SAST + dependency + secrets scan + review
Yes
Testing
Coverage threshold on changed code
Yes
AI
Golden-dataset validation within tolerances
Yes (model work)
Observability
Logs/metrics/traces/alerts present
Yes
Docs/DoD
All applicable DoD items satisfied
Yes

# Appendix B — Traceability
Standard
Traces to
Coding standards
P1 (quality over speed)
API standards
Book 2 Ch. 7
Data + provenance
ENG-001/002, TRUST-001
Security & privacy
ENG-003, TRUST-002, Book 0 §11
Testing & AI validation
ENG-007, SR-003, Book 0 §8
DevOps/CI-CD
Book 2 Ch. 8
Observability
Book 2 Ch. 9
Definition of Done
All modules (Volume 6+)

# Appendix C — Glossary & Acronyms
Term / Acronym
Meaning
RFC 2119
Standard defining MUST/SHOULD/MAY normative language
SAST
Static Application Security Testing
IaC
Infrastructure as Code
Golden dataset
Curated, ground-truth validation set for model accuracy
Tolerance band
Allowed error vs ground truth for a metric class
Canary rollout
Gradual release to a subset before full deployment
RPO / RTO
Recovery Point / Time Objective for backups
Definition of Done
The complete acceptance gate for a unit of work
Provenance label
measured / estimated / modelled tag on a quantity

| Field | Value |
| Document ID | CIP-B3-STD |
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

| Standard area | Enforced by |
| Coding | Linters, formatters, code review, CI gates |
| API | Contract tests, schema linting, versioning checks |
| Data | Migration review, schema registry compatibility checks |
| Security | SAST/dependency scans, security review, secrets scanning |
| Testing / AI | Coverage gates, golden-dataset validation gates |
| Docs / DoD | PR checklist, module acceptance criteria |

| Layer | Standard | Notes |
| Backend / services | Python (FastAPI) | One primary backend language; async where I/O-bound |
| ML / vision | Python (PyTorch, OpenCV) | Shared language with backend simplifies the team |
| Web frontend | TypeScript + Next.js/React + Tailwind | Type-safe UI; SSR where beneficial |
| Mobile | React Native (TypeScript) | One codebase for iOS/Android capture app |

| HTTP | Meaning in CIP |
| 400 | Malformed request |
| 401 / 403 | Unauthenticated / unauthorised (RBAC) |
| 409 | Idempotency or state conflict |
| 422 | Valid request, unprocessable (e.g. clip fails quality gate) |
| 202 | Accepted; analysis running / provisional result |
| 429 | Rate limit exceeded |

| Level | Requirement |
| Unit | MUST cover business logic and every analytical formula against hand-computed fixtures (min 3 cases each: typical, boundary, degenerate) |
| Integration | MUST verify service + datastore + event contracts |
| Contract | MUST verify API/event schemas between producer and consumer |
| End-to-end | SHOULD verify the full upload→report pipeline on sample clips |
| AI evaluation | MUST validate models against a versioned golden dataset with defined tolerances |

| # | Definition-of-Done criterion |
| 1 | Functional implementation meeting the module's acceptance criteria |
| 2 | Unit tests (incl. formula fixtures) passing at required coverage |
| 3 | Integration + contract tests passing |
| 4 | AI validation passed against the golden dataset (for model work) |
| 5 | API/event contracts published and versioned |
| 6 | Security review + scans clean; provenance labels present (TRUST-001) |
| 7 | Performance within the stage's latency/throughput budget |
| 8 | Observability wired (logs, metrics, traces, alerts) |
| 9 | User + API documentation updated |
| 10 | Accessibility review for user-facing surfaces (WCAG 2.1 AA) |

| Area | Gate | Blocking? |
| Coding | Lint + type-check + review | Yes |
| API | Contract tests + version check | Yes |
| Data | Migration review + schema compatibility | Yes |
| Security | SAST + dependency + secrets scan + review | Yes |
| Testing | Coverage threshold on changed code | Yes |
| AI | Golden-dataset validation within tolerances | Yes (model work) |
| Observability | Logs/metrics/traces/alerts present | Yes |
| Docs/DoD | All applicable DoD items satisfied | Yes |

| Standard | Traces to |
| Coding standards | P1 (quality over speed) |
| API standards | Book 2 Ch. 7 |
| Data + provenance | ENG-001/002, TRUST-001 |
| Security & privacy | ENG-003, TRUST-002, Book 0 §11 |
| Testing & AI validation | ENG-007, SR-003, Book 0 §8 |
| DevOps/CI-CD | Book 2 Ch. 8 |
| Observability | Book 2 Ch. 9 |
| Definition of Done | All modules (Volume 6+) |

| Term / Acronym | Meaning |
| RFC 2119 | Standard defining MUST/SHOULD/MAY normative language |
| SAST | Static Application Security Testing |
| IaC | Infrastructure as Code |
| Golden dataset | Curated, ground-truth validation set for model accuracy |
| Tolerance band | Allowed error vs ground truth for a metric class |
| Canary rollout | Gradual release to a subset before full deployment |
| RPO / RTO | Recovery Point / Time Objective for backups |
| Definition of Done | The complete acceptance gate for a unit of work |
| Provenance label | measured / estimated / modelled tag on a quantity |