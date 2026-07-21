CRICKET INTELLIGENCE PLATFORM
CIP BLUEPRINT
BOOK 2
CIP Reference Architecture
Services, data flows, the intelligence pipeline, and how the platform fits together
Document ID: CIP-B2-ARC
Version: 1.0   ·   Status: Draft
Owner: CIP Labs  ·  Prepared for: Indrajit  ·  July 2026
CONFIDENTIAL — Founding Documentation

# Document Control
Field
Value
Document ID
CIP-B2-ARC
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
- Book 0 — CIP Manifesto (principles, Trust Doctrine)
- Book 1 — GCIR (requirements register: ENG-001..007, SR-001..005, TRUST-001..002)

## Feeds Into (Downstream)
- Book 3 — Engineering Standards
- Book 4 — Cricket Intelligence Standards (CIP-STD)
- All module specifications (Volume 6+): M01–M15

# Contents
- Chapter 1 — Architectural Overview & Principles
- Chapter 2 — Service Inventory
- Chapter 3 — The Intelligence Pipeline (End-to-End Data Flow)
- Chapter 4 — Event-Driven Architecture & Message Contracts
- Chapter 5 — Data Architecture & Multi-Tenancy
- Chapter 6 — The Seven Engines as Services
- Chapter 7 — API Architecture
- Chapter 8 — Deployment, Infrastructure & Scaling
- Chapter 9 — Cross-Cutting Concerns (Security, Observability, MLOps)
- Appendix A — Service Register
- Appendix B — Architecture Requirements Traceability
- Appendix C — Glossary & Acronyms

# Chapter 1 — Architectural Overview & Principles
Document ID: ARC-CH-001
## 1.1 Purpose
Book 1 established what CIP must do and why. This volume defines how the platform is structured so that those requirements are satisfied in a scalable, maintainable, and independently deployable way. It is the authoritative reference every module specification builds upon.
## 1.2 Architectural Style
CIP adopts an event-driven microservices architecture organised by domain. This directly satisfies ENG-004 (separable vision, biomechanics, physics, reasoning services) and enables the platform to scale its expensive components (GPU inference) independently of its cheap ones (web APIs).
Decision
Choice
Rationale (traces to)
Service style
Domain-oriented microservices
ENG-004 — separable analytical services
Communication
Async events for the pipeline; REST/gRPC for queries
Video analysis is a background job, not a live request
Coupling
Loose; services own their data
Independent deploy, test, and scale
State
Stateless compute; state in datastores/queues
Horizontal scaling, resilience
Tenancy
Multi-tenant with strict isolation
ENG-001, ENG-003
Explainability
Evidence carried through every stage
ENG-005, TRUST-001
## 1.3 The Four Planes
The platform is reasoned about as four planes, from the user down to the data:
Plane
Contains
Responsibility
Experience Plane
Mobile app, web dashboard, coach & academy consoles
Capture, delivery, interaction
Application Plane
API gateway, orchestration, SaaS services (auth, billing, profiles)
Product logic, access, workflow
Intelligence Plane
Vision Foundation + the seven Engines
Turning video into explained coaching
Data Plane
Object storage, databases, event bus, model registry, data lake
Persistence, streaming, training data
### Research Findings
- Event-driven microservices best fit CIP's mix of expensive async analysis and cheap synchronous queries.
- A four-plane model gives every service a clear home.
### Business Implications
- Independent scaling controls cloud cost — the biggest operational lever.
- Modularity lets the roadmap ship one engine at a time (aligns with phased plan).
### Engineering Implications
- Services own their data; no shared database.
- The pipeline is asynchronous end to end.
- Every stage must propagate evidence and provenance labels.
### AI Implications
- Model-serving services are isolated so GPU pools scale independently.
- A model registry governs versioned, rollback-able models (ENG-007).
### Future Research Questions
- Where is the boundary between orchestration logic and engine logic?
- Which services justify gRPC over REST for latency?
### Traceability
- Implements ENG-001, ENG-003, ENG-004, ENG-005, ENG-007.
- Feeds every module spec's architecture section.

# Chapter 2 — Service Inventory
Document ID: ARC-CH-002
The platform is composed of the following services, grouped by plane. Each is independently deployable and owns its data. Module numbers (Mxx) link to the Volume 6+ specifications.
## 2.1 SaaS / Application Services
Service
Module
Responsibility
Identity & Auth
M02
Registration, login, OAuth, RBAC, multi-tenant routing
Subscription & Billing
M03
Plans, metering, invoices, dunning
Player Profile
M04
Persistent player identity & longitudinal history (Cricket DNA store)
Academy / Coach
M18
Team management, coach console, parent reports
Notification
M19
Email/push/in-app alerts
Admin & Platform Analytics
M20
Internal ops, usage, model monitoring
## 2.2 Vision Foundation Services
Service
Module
Responsibility
Video Intelligence
M05
Ingestion, stabilisation, normalisation, quality gate, capture guidance
Pose Engine
M06
Per-frame body keypoints + confidence
Bat Detection
M07
Bat/handle/blade/sweet-spot/angle tracking
Ball Tracking
M08
Release, bounce, line, length, contact, speed
Shot Recognition
M09
Shot classification + phase segmentation
## 2.3 Intelligence Engine Services
Service
Module
Responsibility
Biomechanics Engine
M10
2D/3D angles, rotations, timing (MEASURED)
Physics Engine
M11
Kinematics (measured) + dynamics (estimated)
Cricket Knowledge Graph
M12
Coaching cause-effect ontology & rule host
Reasoning Engine
M13
Evidence-based inference over facts + rules
Report Generator / AI Coach
M14
Explained report + LLM coach (RAG)
Benchmark Intelligence
M15
Comparison to reference/legend benchmarks
Cricket DNA
M16
Longitudinal trait profile & update job
Learning Engine
M17
Learning-stage inference, drill optimisation
### Research Findings
- ~19 services span three functional groups (SaaS, Vision, Intelligence).
- Each maps to exactly one module specification.
### Business Implications
- The service map doubles as the delivery backlog — each is a shippable unit.
### Engineering Implications
- No service shares another's database.
- Vision services are GPU-bound; SaaS services are not — schedule them on separate node pools.
### AI Implications
- Engine services consume Vision outputs as structured facts, never raw video (except Video Intelligence).
### Future Research Questions
- Should Reasoning and Report Generator merge or stay separate?
- Is Benchmark a service or a library inside Reasoning?
### Traceability
- Defines the module set M01–M20 for Volume 6+.
- Satisfies ENG-004.

# Chapter 3 — The Intelligence Pipeline (End-to-End Data Flow)
Document ID: ARC-CH-003
This is the spine of the platform: how a single uploaded batting video becomes an explained coaching report. Each arrow is an asynchronous handoff carrying structured data plus provenance labels (TRUST-001).

1. Mobile app → upload clip + capture metadata
2. Video Intelligence (M05) → normalised clip + quality gate + calibration
3. Pose Engine (M06) → keypoints/frame        ┐
4. Bat Detection (M07) → bat keypoints         ├→ (parallel)
5. Ball Tracking (M08) → ball events           ┘
6. Shot Recognition (M09) → shot type + phases
7. Biomechanics Engine (M10) → MEASURED metrics
8. Physics Engine (M11) → kinematics + ESTIMATED dynamics
9. Benchmark Intelligence (M15) → gaps vs reference profiles
10. Knowledge Graph (M12) + Reasoning (M13) → why + match consequence
11. Report Generator / AI Coach (M14) → explained report + drills
12. Cricket DNA (M16) update ← report; Learning Engine (M17) tunes plan
13. Notification (M19) → player & coach; Dashboard renders annotated video

## 3.1 Quality gating & graceful degradation
Per Book 0 and the biomechanics contract, the pipeline degrades gracefully: if bat/ball tracking confidence is low, dependent metrics are marked provisional and the report proceeds with adjusted weighting rather than failing. Every stage emits quality flags that travel with the payload.
## 3.2 Latency budget
Stage group
Target
Notes
Preprocess (M05)
3–8 s
Transcode + normalise + calibrate
Vision (M06–M09)
20–40 s
GPU-bound; the dominant cost
Analytics (M10–M11)
≤ 3 s
CPU numerical compute
Reasoning + Report (M12–M14)
5–10 s
Includes LLM call
End-to-end
< 60 s
Success metric from v1 PRD
### Research Findings
- The pipeline is linear with one parallel fan-out (pose/bat/ball).
- Vision dominates the latency and cost budget.
### Business Implications
- Sub-60s end-to-end is a marketable SLA and a real engineering constraint.
### Engineering Implications
- Stages communicate via events with idempotency keys.
- Provenance labels and quality flags are mandatory payload fields.
### AI Implications
- Parallelising pose/bat/ball requires independent model-serving endpoints.
- The LLM step is grounded (RAG) on Knowledge Graph facts, never free-form.
### Future Research Questions
- Can bat/ball tracking be deferred to a second pass to cut first-report latency?
- What is the retry/DLQ policy per stage?
### Traceability
- Implements ENG-005 (evidence propagation) and the <60s success metric.
- Feeds Modules M05–M17.

# Chapter 4 — Event-Driven Architecture & Message Contracts
Document ID: ARC-CH-004
## 4.1 Topics
The pipeline is coordinated through an event bus (e.g. Kafka or a managed equivalent). Each stage subscribes to its input topic and publishes to its output topic. A schema registry enforces contract compatibility.
Topic
Produced by
Consumed by
video.uploaded
Mobile/API
Video Intelligence
video.normalized
Video Intelligence
Pose, Bat, Ball, Shot
pose.keypoints / bat.tracked / ball.events
Vision services
Biomechanics, Shot Recognition
biomechanics.metrics
Biomechanics
Physics, Benchmark, Reasoning
physics.metrics
Physics
Benchmark, Reasoning
analysis.reasoned
Reasoning
Report Generator
report.ready
Report Generator
Notification, DNA, Dashboard
## 4.2 Contract rules
- Every message carries: correlation_id (the stroke/session), schema_version, produced_at, and quality/provenance fields.
- Consumers must be idempotent; the same event may be delivered more than once.
- Failed processing routes to a per-stage dead-letter queue (DLQ) with retry policy; never silently dropped.
- Schema changes must be backward-compatible or introduce a new versioned topic.
### Research Findings
- Async events decouple stages and absorb load spikes.
- A schema registry is the guardrail against breaking changes.
### Business Implications
- Resilience (retry/DLQ) protects the user experience and paid SLAs.
### Engineering Implications
- Idempotency and correlation IDs are mandatory.
- DLQs are monitored; backlog is an alertable metric.
### AI Implications
- Model output schemas are versioned like any other contract.
### Future Research Questions
- Exactly-once vs at-least-once for the report stage?
- Topic partitioning key — by player, session, or stroke?
### Traceability
- Defines the contracts Modules M05–M14 must implement.
- Feeds Book 3 (Engineering Standards).

# Chapter 5 — Data Architecture & Multi-Tenancy
Document ID: ARC-CH-005
## 5.1 Datastores
Store
Technology (indicative)
Holds
Relational DB
PostgreSQL
Users, tenants, profiles, sessions, subscriptions, metrics metadata
Object storage
S3 / GCS
Raw + normalised video, annotated renders, pose/bat/ball artefacts
Cache / queue state
Redis
Sessions, rate limits, job coordination
Event bus
Kafka / managed
Pipeline topics
Model registry
MLflow / equivalent
Versioned models + metadata (ENG-007)
Analytics lake / warehouse
Columnar store
Longitudinal analytics, training-data curation
## 5.2 Multi-Tenancy (ENG-001, ENG-002, ENG-003)
A tenant is an organisation (academy, association, team) or an individual account. Isolation is enforced at the data layer (row-level security keyed by tenant_id) and the access layer (RBAC). Crucially, a player's identity and Cricket DNA persist independently of any single tenant, so history survives when a player changes academy or coach — the core problem identified in Book 1, Chapter 2.
Concern
Mechanism
Tenant isolation
tenant_id on every row; row-level security; per-tenant object-storage prefixes
Player portability
Global player identity separate from tenant membership; consent-governed data sharing
Access control
RBAC roles: player, parent, coach, academy_admin, org_admin, platform_admin
Minors' data
Guardian consent flags; restricted processing; jurisdiction-aware residency
### Research Findings
- Player identity must be modelled independently of tenants to solve the 'history reset' problem.
- Video is the storage cost driver; lifecycle tiering is essential.
### Business Implications
- Player portability is both a user benefit and a moat (data follows the player, into CIP).
### Engineering Implications
- Row-level security keyed by tenant_id; no cross-tenant leakage.
- Object storage lifecycle rules tier old video to cold storage.
### AI Implications
- The analytics lake is the curation ground for the proprietary training dataset.
### Future Research Questions
- Data-residency partitioning strategy for EU/India/AU?
- How is consent propagated when a player moves academies?
### Traceability
- Implements ENG-001, ENG-002, ENG-003; Book 0 §11.1 (minors).
- Feeds Modules M02, M04, M18.

# Chapter 6 — The Seven Engines as Services
Document ID: ARC-CH-006
The founder's seven Intelligence Engines are realised as cooperating services on the Intelligence Plane. This chapter fixes their interfaces and integration so each can be built independently while composing into the explainable chain.
Engine
Service module
Consumes
Produces
Physics
M11
biomechanics.metrics
kinematics (measured) + dynamics (estimated) + confidence
Cricket Knowledge Graph
M12
metrics + physics facts
matched rules: cause → risk → drill
Batting DNA
M16
report.ready (all sessions)
updated longitudinal trait profile
Match Intelligence
M13*
DNA + rules + context
vulnerability by delivery type (MODELLED)
Learning Engine
M17
longitudinal outcomes
learning stage + optimised drill plan
Digital Twin
M-future
many sessions
simulated performance (research, Phase 4)
Cricket GPT
M14
report + history + KG (RAG)
conversational, grounded coaching answers
*Match Intelligence is delivered within/alongside the Reasoning Engine (M13) as its tactical capability matures. Legend Comparison is provided by Benchmark Intelligence (M15) and consumed by the Report Generator and Cricket GPT.
### Research Findings
- The seven engines map cleanly onto services already in the inventory — no new plane needed.
- Legend Comparison is a cross-engine capability (Benchmark + Physics + DNA).
### Business Implications
- Engines can be sequenced by phase (Physics/Benchmark first) without re-architecting.
### Engineering Implications
- Each engine exposes a versioned internal API and an event contract.
- Digital Twin is isolated as future research; nothing depends on it at launch.
### AI Implications
- Cricket GPT is strictly RAG-grounded on Knowledge Graph + player evidence (ENG-005).
### Future Research Questions
- Does Match Intelligence warrant its own service once data volume grows?
- How are benchmark profiles versioned alongside models?
### Traceability
- Realises the seven-engine vision (Book 0 §4, Seven-Engine Architecture doc).
- Feeds Modules M11–M17.

# Chapter 7 — API Architecture
Document ID: ARC-CH-007
## 7.1 Edge
A single API gateway fronts all client traffic: authentication, rate limiting, request routing, and API versioning. Public/partner access (Enterprise tier) is served through a separately governed Partner API with its own keys and quotas.
## 7.2 Standards (defined fully in Book 3)
- Versioned endpoints (e.g. /v1/...); no breaking changes within a version.
- Consistent error envelope; idempotency keys on mutating calls.
- Cursor-based pagination; explicit rate-limit headers.
- Internal service APIs may use gRPC where latency matters; external APIs are REST/JSON.
## 7.3 Representative external endpoints
Method & path
Purpose
POST /v1/videos
Create upload + get storage URL
POST /v1/analyses
Trigger analysis for an uploaded clip
GET /v1/analyses/{id}
Fetch report + provenance-labelled metrics
GET /v1/players/{id}/dna
Fetch Cricket DNA profile
GET /v1/players/{id}/progress
Longitudinal trends
POST /v1/coach/messages
Ask Cricket GPT (grounded)
### Research Findings
- A gateway centralises auth, rate limiting, and versioning.
- Enterprise access needs a separately governed Partner API.
### Business Implications
- The Partner/Performance API is itself a revenue stream (Book 0 §9 model).
### Engineering Implications
- REST/JSON externally, gRPC internally where justified.
- Idempotency and versioning are mandatory.
### AI Implications
- The coach endpoint enforces RAG grounding and safety guardrails server-side.
### Future Research Questions
- Rate-limit tiers per subscription plan?
- Webhook contract for async report.ready notifications to partners?
### Traceability
- Feeds Book 3 (API standards) and Modules M02, M05, M14, M15.

# Chapter 8 — Deployment, Infrastructure & Scaling
Document ID: ARC-CH-008
## 8.1 Runtime
Services run in containers orchestrated by Kubernetes (or a managed equivalent). Two node-pool classes separate the cost profiles: a CPU pool for SaaS/analytics services, and a GPU pool (NVIDIA L4/T4 class) for Vision model serving that scales to zero when idle.
Concern
Approach
Environments
dev / staging / production, isolated
GPU scaling
Autoscale on queue depth; scale to zero when idle; spot/preemptible for training
CPU scaling
Horizontal pod autoscaling on CPU/latency
Cloud
Single primary cloud for MVP (avoid multi-cloud overhead); region strategy for residency
Cost control
Per-video variable cost ~$0.03–0.08; idle GPU is the main risk — mitigated by scale-to-zero
## 8.2 Resilience
Stateless services + queue-backed pipeline mean a failed worker simply causes redelivery. Datastores are backed up with defined RPO/RTO (detailed in Book 3). No single video analysis is ever lost silently — it either completes, degrades gracefully, or lands in a DLQ for inspection.
### Research Findings
- Separating CPU and GPU node pools is the primary cost-control lever.
- Queue-backed statelessness gives resilience cheaply.
### Business Implications
- Scale-to-zero GPU keeps early-stage burn low, matching the feasibility study's cost model.
### Engineering Implications
- Single cloud for MVP; multi-region only for residency.
- Infrastructure as code; reproducible environments.
### AI Implications
- Training uses spot/preemptible GPUs; serving uses on-demand autoscaled pools.
### Future Research Questions
- Managed Kubernetes vs serverless GPU for early scale?
- When does multi-region become mandatory (which market first)?
### Traceability
- Implements the <60s SLA and the feasibility cost model.
- Feeds Book 3 (DevOps/observability) and Module M01.

# Chapter 9 — Cross-Cutting Concerns
Document ID: ARC-CH-009
## 9.1 Security & Privacy
- JWT/OAuth authentication; RBAC authorisation; encryption in transit and at rest.
- Per-tenant isolation; least-privilege service credentials; audit logging of sensitive actions.
- Minors' data handling and consent flows as first-order requirements (Book 0 §11.1).
## 9.2 Observability
- Structured logging, metrics, and distributed tracing across the pipeline via correlation_id.
- SLOs per stage; alerting on latency, error rate, and DLQ backlog.
## 9.3 MLOps (ENG-007)
- Versioned models in a registry; canary rollout and instant rollback.
- Drift monitoring; a research-grade validation framework gating releases against golden datasets.
- Every model output labelled measured/estimated/modelled (TRUST-001).
### Research Findings
- Security, observability, and MLOps are platform-wide, not per-service afterthoughts.
### Business Implications
- Auditability and validation are prerequisites for academy and governing-body trust.
### Engineering Implications
- correlation_id threads tracing through the whole async pipeline.
- Release gates block model regressions.
### AI Implications
- Golden-dataset validation is the objective bar for shipping any model change.
### Future Research Questions
- Which SLOs are contractual for Academy/Enterprise tiers?
- Model-card standard for each deployed model?
### Traceability
- Implements ENG-007, TRUST-001; Book 0 §11.
- Feeds Book 3 in full.

# Appendix A — Service Register
Module
Service
Plane
Compute
M01
Platform Foundation
Application
CPU
M02
Identity & Auth
Application
CPU
M03
Subscription & Billing
Application
CPU
M04
Player Profile
Application
CPU
M05
Video Intelligence
Intelligence
CPU+GPU
M06
Pose Engine
Intelligence
GPU
M07
Bat Detection
Intelligence
GPU
M08
Ball Tracking
Intelligence
GPU
M09
Shot Recognition
Intelligence
GPU/CPU
M10
Biomechanics Engine
Intelligence
CPU
M11
Physics Engine
Intelligence
CPU
M12
Cricket Knowledge Graph
Intelligence
CPU
M13
Reasoning Engine
Intelligence
CPU
M14
Report Generator / AI Coach
Intelligence
CPU + LLM API
M15
Benchmark Intelligence
Intelligence
CPU
M16
Cricket DNA
Intelligence
CPU
M17
Learning Engine
Intelligence
CPU
M18
Academy / Coach
Application
CPU
M19
Notification
Application
CPU
M20
Admin & Analytics
Application
CPU

# Appendix B — Architecture Requirements Traceability
Requirement
Satisfied by
ENG-001 Multi-tenant
Ch. 5 (row-level security, tenant isolation)
ENG-002 Persistent player identity
Ch. 5 (global player identity, portability)
ENG-003 RBAC
Ch. 5, Ch. 9 (roles, access layer)
ENG-004 Separable services
Ch. 1, Ch. 2 (microservice inventory)
ENG-005 Explainable pipeline
Ch. 3, Ch. 4 (evidence propagation, contracts)
ENG-006 Benchmark first-class
Ch. 2, Ch. 6 (M15 as a service)
ENG-007 Versioned models + validation
Ch. 9 (MLOps, golden-dataset gates)
TRUST-001 Provenance labels
Ch. 3, Ch. 4, Ch. 9
TRUST-002 Legend benchmarks
Ch. 6 (M15 derived benchmarks)
SR-001..005 Learning-aware
Ch. 6 (M16 DNA, M17 Learning Engine)

# Appendix C — Glossary & Acronyms
Term / Acronym
Meaning
Plane
A horizontal layer of the architecture (Experience/Application/Intelligence/Data)
Event bus
Asynchronous messaging backbone coordinating the pipeline
DLQ
Dead-letter queue — holds messages that failed processing
Idempotency
Property where reprocessing the same event causes no duplicate effect
correlation_id
Identifier threading one stroke/session through all stages
RBAC
Role-Based Access Control
MLOps
Practices for versioning, deploying, and monitoring ML models
Provenance label
measured / estimated / modelled tag on every quantity
Node pool
A group of compute nodes with a shared profile (CPU vs GPU)

| Field | Value |
| Document ID | CIP-B2-ARC |
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

| Decision | Choice | Rationale (traces to) |
| Service style | Domain-oriented microservices | ENG-004 — separable analytical services |
| Communication | Async events for the pipeline; REST/gRPC for queries | Video analysis is a background job, not a live request |
| Coupling | Loose; services own their data | Independent deploy, test, and scale |
| State | Stateless compute; state in datastores/queues | Horizontal scaling, resilience |
| Tenancy | Multi-tenant with strict isolation | ENG-001, ENG-003 |
| Explainability | Evidence carried through every stage | ENG-005, TRUST-001 |

| Plane | Contains | Responsibility |
| Experience Plane | Mobile app, web dashboard, coach & academy consoles | Capture, delivery, interaction |
| Application Plane | API gateway, orchestration, SaaS services (auth, billing, profiles) | Product logic, access, workflow |
| Intelligence Plane | Vision Foundation + the seven Engines | Turning video into explained coaching |
| Data Plane | Object storage, databases, event bus, model registry, data lake | Persistence, streaming, training data |

| Service | Module | Responsibility |
| Identity & Auth | M02 | Registration, login, OAuth, RBAC, multi-tenant routing |
| Subscription & Billing | M03 | Plans, metering, invoices, dunning |
| Player Profile | M04 | Persistent player identity & longitudinal history (Cricket DNA store) |
| Academy / Coach | M18 | Team management, coach console, parent reports |
| Notification | M19 | Email/push/in-app alerts |
| Admin & Platform Analytics | M20 | Internal ops, usage, model monitoring |

| Service | Module | Responsibility |
| Video Intelligence | M05 | Ingestion, stabilisation, normalisation, quality gate, capture guidance |
| Pose Engine | M06 | Per-frame body keypoints + confidence |
| Bat Detection | M07 | Bat/handle/blade/sweet-spot/angle tracking |
| Ball Tracking | M08 | Release, bounce, line, length, contact, speed |
| Shot Recognition | M09 | Shot classification + phase segmentation |

| Service | Module | Responsibility |
| Biomechanics Engine | M10 | 2D/3D angles, rotations, timing (MEASURED) |
| Physics Engine | M11 | Kinematics (measured) + dynamics (estimated) |
| Cricket Knowledge Graph | M12 | Coaching cause-effect ontology & rule host |
| Reasoning Engine | M13 | Evidence-based inference over facts + rules |
| Report Generator / AI Coach | M14 | Explained report + LLM coach (RAG) |
| Benchmark Intelligence | M15 | Comparison to reference/legend benchmarks |
| Cricket DNA | M16 | Longitudinal trait profile & update job |
| Learning Engine | M17 | Learning-stage inference, drill optimisation |

| Stage group | Target | Notes |
| Preprocess (M05) | 3–8 s | Transcode + normalise + calibrate |
| Vision (M06–M09) | 20–40 s | GPU-bound; the dominant cost |
| Analytics (M10–M11) | ≤ 3 s | CPU numerical compute |
| Reasoning + Report (M12–M14) | 5–10 s | Includes LLM call |
| End-to-end | < 60 s | Success metric from v1 PRD |

| Topic | Produced by | Consumed by |
| video.uploaded | Mobile/API | Video Intelligence |
| video.normalized | Video Intelligence | Pose, Bat, Ball, Shot |
| pose.keypoints / bat.tracked / ball.events | Vision services | Biomechanics, Shot Recognition |
| biomechanics.metrics | Biomechanics | Physics, Benchmark, Reasoning |
| physics.metrics | Physics | Benchmark, Reasoning |
| analysis.reasoned | Reasoning | Report Generator |
| report.ready | Report Generator | Notification, DNA, Dashboard |

| Store | Technology (indicative) | Holds |
| Relational DB | PostgreSQL | Users, tenants, profiles, sessions, subscriptions, metrics metadata |
| Object storage | S3 / GCS | Raw + normalised video, annotated renders, pose/bat/ball artefacts |
| Cache / queue state | Redis | Sessions, rate limits, job coordination |
| Event bus | Kafka / managed | Pipeline topics |
| Model registry | MLflow / equivalent | Versioned models + metadata (ENG-007) |
| Analytics lake / warehouse | Columnar store | Longitudinal analytics, training-data curation |

| Concern | Mechanism |
| Tenant isolation | tenant_id on every row; row-level security; per-tenant object-storage prefixes |
| Player portability | Global player identity separate from tenant membership; consent-governed data sharing |
| Access control | RBAC roles: player, parent, coach, academy_admin, org_admin, platform_admin |
| Minors' data | Guardian consent flags; restricted processing; jurisdiction-aware residency |

| Engine | Service module | Consumes | Produces |
| Physics | M11 | biomechanics.metrics | kinematics (measured) + dynamics (estimated) + confidence |
| Cricket Knowledge Graph | M12 | metrics + physics facts | matched rules: cause → risk → drill |
| Batting DNA | M16 | report.ready (all sessions) | updated longitudinal trait profile |
| Match Intelligence | M13* | DNA + rules + context | vulnerability by delivery type (MODELLED) |
| Learning Engine | M17 | longitudinal outcomes | learning stage + optimised drill plan |
| Digital Twin | M-future | many sessions | simulated performance (research, Phase 4) |
| Cricket GPT | M14 | report + history + KG (RAG) | conversational, grounded coaching answers |

| Method & path | Purpose |
| POST /v1/videos | Create upload + get storage URL |
| POST /v1/analyses | Trigger analysis for an uploaded clip |
| GET /v1/analyses/{id} | Fetch report + provenance-labelled metrics |
| GET /v1/players/{id}/dna | Fetch Cricket DNA profile |
| GET /v1/players/{id}/progress | Longitudinal trends |
| POST /v1/coach/messages | Ask Cricket GPT (grounded) |

| Concern | Approach |
| Environments | dev / staging / production, isolated |
| GPU scaling | Autoscale on queue depth; scale to zero when idle; spot/preemptible for training |
| CPU scaling | Horizontal pod autoscaling on CPU/latency |
| Cloud | Single primary cloud for MVP (avoid multi-cloud overhead); region strategy for residency |
| Cost control | Per-video variable cost ~$0.03–0.08; idle GPU is the main risk — mitigated by scale-to-zero |

| Module | Service | Plane | Compute |
| M01 | Platform Foundation | Application | CPU |
| M02 | Identity & Auth | Application | CPU |
| M03 | Subscription & Billing | Application | CPU |
| M04 | Player Profile | Application | CPU |
| M05 | Video Intelligence | Intelligence | CPU+GPU |
| M06 | Pose Engine | Intelligence | GPU |
| M07 | Bat Detection | Intelligence | GPU |
| M08 | Ball Tracking | Intelligence | GPU |
| M09 | Shot Recognition | Intelligence | GPU/CPU |
| M10 | Biomechanics Engine | Intelligence | CPU |
| M11 | Physics Engine | Intelligence | CPU |
| M12 | Cricket Knowledge Graph | Intelligence | CPU |
| M13 | Reasoning Engine | Intelligence | CPU |
| M14 | Report Generator / AI Coach | Intelligence | CPU + LLM API |
| M15 | Benchmark Intelligence | Intelligence | CPU |
| M16 | Cricket DNA | Intelligence | CPU |
| M17 | Learning Engine | Intelligence | CPU |
| M18 | Academy / Coach | Application | CPU |
| M19 | Notification | Application | CPU |
| M20 | Admin & Analytics | Application | CPU |

| Requirement | Satisfied by |
| ENG-001 Multi-tenant | Ch. 5 (row-level security, tenant isolation) |
| ENG-002 Persistent player identity | Ch. 5 (global player identity, portability) |
| ENG-003 RBAC | Ch. 5, Ch. 9 (roles, access layer) |
| ENG-004 Separable services | Ch. 1, Ch. 2 (microservice inventory) |
| ENG-005 Explainable pipeline | Ch. 3, Ch. 4 (evidence propagation, contracts) |
| ENG-006 Benchmark first-class | Ch. 2, Ch. 6 (M15 as a service) |
| ENG-007 Versioned models + validation | Ch. 9 (MLOps, golden-dataset gates) |
| TRUST-001 Provenance labels | Ch. 3, Ch. 4, Ch. 9 |
| TRUST-002 Legend benchmarks | Ch. 6 (M15 derived benchmarks) |
| SR-001..005 Learning-aware | Ch. 6 (M16 DNA, M17 Learning Engine) |

| Term / Acronym | Meaning |
| Plane | A horizontal layer of the architecture (Experience/Application/Intelligence/Data) |
| Event bus | Asynchronous messaging backbone coordinating the pipeline |
| DLQ | Dead-letter queue — holds messages that failed processing |
| Idempotency | Property where reprocessing the same event causes no duplicate effect |
| correlation_id | Identifier threading one stroke/session through all stages |
| RBAC | Role-Based Access Control |
| MLOps | Practices for versioning, deploying, and monitoring ML models |
| Provenance label | measured / estimated / modelled tag on every quantity |
| Node pool | A group of compute nodes with a shared profile (CPU vs GPU) |