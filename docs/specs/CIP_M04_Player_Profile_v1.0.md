# Module M04 — Player Profile

**CIP Blueprint · Volume 6 (Module Specifications)**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M04-PRF |
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
- Module M02 — Identity & Authentication (global person identity, consent, RBAC)
- Book 2 — Reference Architecture (Application Plane; ENG-002 persistent identity)
- Book 3 — Engineering Standards (data, security, DoD)
- Book 4 — CIP-STD (metric IDs; personal-baseline concept)

**Feeds Into (Downstream)**

- M10 Biomechanics Engine (consumes anthropometrics: height, stance, age band)
- M15 Benchmark Intelligence (personal baseline); M16 Cricket DNA (writes trait updates)
- M17 Learning Engine; M18 Academy/Coach; Progress Analytics; M14 Report Generator

---

## Contents

1. Executive Summary
2. Business Context
3. Scope & Responsibilities
4. Personas & Users
5. The Player Profile & Cricket DNA Data Model
6. Functional Requirements
7. Non-Functional Requirements
8. Architecture
9. Database Design
10. API Specification
11. Consent, Privacy & Portability
12. Security
13. Testing Strategy
14. Deployment & Monitoring
15. Future Enhancements
16. Claude Code Implementation Guide
17. Acceptance Criteria
18. Appendix — Glossary

---

## 1. Executive Summary

Module M04, Player Profile, is the canonical, long-lived record of a cricketer. It holds three things: the player's **attributes** (anthropometrics such as height, batting stance/handedness, and age band), the player's **Cricket DNA** (the current values and history of their technical traits), and an **index of their longitudinal history** (sessions, analyses, and reports over time). It is the memory of the platform — the component that makes a player's development a continuous story rather than a series of disconnected reports.

M04 is a store and a set of access APIs; it does not *compute* trait values. The Cricket DNA engine (M16) computes trait updates from each report and writes them into M04. Other modules read from M04: the Biomechanics Engine (M10) needs the player's height and stance to compute metrics correctly; Benchmark Intelligence (M15) needs the player's personal baseline; the Report Generator (M14) needs history to describe improvement.

Because Book 1 mandated that a player's technical history must survive changing coaches or academies (ENG-002), M04 is deliberately anchored to the **global person identity** in M02, not to any tenant.

## 2. Business Context

The central problem identified in Book 1, Chapter 2 is that a player's technical history is reset whenever they change organisation. M04 solves this: the profile and Cricket DNA belong to the person and persist across academies, subject to consent. This continuity is both the core user benefit (measurable, lifelong progress) and a durable moat (the longitudinal record is proprietary and compounding).

Commercially, M04 underpins progress tracking (a Pro-tier value driver), academy analytics (institutional value), and the personal-baseline comparisons that make improvement visible.

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Player attributes | Anthropometrics: height, stance/handedness, age band, dominant hand |
| Cricket DNA store | Current trait values + versioned history (aggression, balance, power, timing, footwork, etc.) |
| History index | Longitudinal index of sessions/analyses/reports for the player |
| Personal baseline | Per-metric historical distribution served to M15 |
| Profile APIs | Read/write for other modules; progress/trend queries |
| DNA snapshots | Point-in-time, versioned snapshots for auditability and trend charts |
| Consent-governed access | Enforce M02 consent scope on all reads/writes |

### 3.2 Out of scope

- Computing trait updates (M16), running analyses (M05–M14), and rendering dashboards (M12/M18 UI). M04 stores and serves; it does not analyse.

## 4. Personas & Users

| Persona | Need from M04 |
|---|---|
| Player | A lasting profile; visible progress; portable across academies |
| Parent/guardian | Oversee a minor's profile within consent scope |
| Coach | Read assigned players' profiles, DNA, and history |
| Academy admin | Aggregate/roster views built on player profiles |
| Other modules | Read attributes/baseline/history; M16 writes DNA |

## 5. The Player Profile & Cricket DNA Data Model

The Cricket DNA is a structured, versioned set of trait scores plus descriptive style tags. Trait keys are stable (like CIP-STD metric IDs) so history is comparable over time.

| Trait group | Examples (stable keys) |
|---|---|
| Style descriptors | `style.backlift`, `style.stance`, `dominant_side` (front/back foot) |
| Performance traits | `trait.aggression`, `trait.timing`, `trait.balance`, `trait.power`, `trait.footwork` |
| Tendencies | `pref.shots`, `weak.areas`, `trait.shot_selection` |
| Learning traits | `trait.learning_speed`, `trait.consistency`, `trait.reaction_time` |

Each trait stores: current value, confidence, last-updated, and a history series. Attributes (height, stance, age band) are separate from traits because they are inputs to analysis (consumed by M10), not outputs of it.

## 6. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M04-01 | Create and maintain a player profile bound to a global person identity (M02), independent of tenant (ENG-002). |
| FR-M04-02 | Store player attributes (height, stance/handedness, age band) and serve them to authorised modules (e.g. M10). |
| FR-M04-03 | Store Cricket DNA traits with current value, confidence, and versioned history per trait. |
| FR-M04-04 | Accept trait updates from M16 (write path) with provenance and confidence (Book 0 §8). |
| FR-M04-05 | Maintain a longitudinal history index linking the player to sessions/analyses/reports. |
| FR-M04-06 | Serve the player's personal baseline (per-metric distribution) to M15. |
| FR-M04-07 | Provide progress/trend queries (weekly/monthly/yearly) over traits and metrics. |
| FR-M04-08 | Produce point-in-time DNA snapshots (versioned) for audit and trend charts. |
| FR-M04-09 | Enforce M02 consent scope on every read/write; support export and deletion of the profile. |
| FR-M04-10 | Emit `profile.updated` / `dna.updated` events for interested modules (e.g. M18, Progress Analytics). |
| FR-M04-11 | Record profile changes to the M01 `audit_log`. |

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-M04-01 | Attribute/baseline reads used in the analysis pipeline MUST return in <50ms. |
| NFR-M04-02 | Trait history MUST be append-only and reconstructable to any prior point (no destructive overwrite). |
| NFR-M04-03 | All profile data encrypted at rest; PII never in URLs/logs (Book 3, Ch. 5). |
| NFR-M04-04 | Portability: moving/leaving a tenant MUST NOT alter or delete the profile. |
| NFR-M04-05 | Availability ≥ 99.9% for attribute reads (on the analysis critical path). |

## 8. Architecture

M04 is a stateless service on the **Application Plane** owning its datastore. It is written to by M16 (DNA updates) and by the player/coach (attributes), and read by many modules. It is anchored to the M02 person identity, not to a tenant, which is what delivers portability.

```
M02 person ──1:1── M04 profile (attributes + DNA + history index)
M16 Cricket DNA → M04 (write trait updates, versioned)
M10 Biomechanics → M04 (read height/stance/age band)   ← analysis critical path (<50ms)
M15 Benchmark → M04 (read personal baseline)
M14 Report / M18 Academy → M04 (read DNA + history)
```

Boundary (ENG-004): M04 stores and serves; M16 computes. No module writes traits except M16.

## 9. Database Design

| Table | Key columns | Notes |
|---|---|---|
| player_profiles | id, person_id, height_cm, stance, age_band, dominant_hand, created_at | 1:1 with M02 person; attributes for analysis |
| dna_traits | id, profile_id, trait_key, value, confidence, updated_at | Current trait values |
| dna_trait_history | id, profile_id, trait_key, value, confidence, snapshot_at, source_ref | Append-only history (NFR-M04-02) |
| dna_snapshots | id, profile_id, version, taken_at, payload(JSONB) | Point-in-time full-DNA snapshot |
| history_index | id, profile_id, entity_type, entity_ref, occurred_at | Links to sessions/analyses/reports |
| personal_baselines | id, profile_id, metric_key, distribution(JSONB), updated_at | Served to M15 |

`player_profiles.person_id` references the M02 global person (not tenant-scoped). Tenant-scoped visibility is enforced via consent + membership at the access layer, not by owning the row in a tenant.

## 10. API Specification

| Method & path | Purpose |
|---|---|
| POST /v1/players/{personId}/profile | Create/initialise a profile |
| GET /v1/players/{personId}/profile | Read attributes (auth + consent scoped) |
| PATCH /v1/players/{personId}/profile | Update attributes (height/stance/age band) |
| GET /v1/players/{personId}/dna | Read current Cricket DNA |
| POST /v1/players/{personId}/dna | Internal: M16 writes trait updates |
| GET /v1/players/{personId}/dna/history | Trait history / snapshots |
| GET /v1/players/{personId}/baseline | Internal: personal baseline for M15 |
| GET /v1/players/{personId}/progress | Trend query (period-scoped) |
| GET /v1/players/{personId}/attributes | Internal fast read for M10 (<50ms) |

Standards: versioned paths, standard error envelope, consent enforcement on every call (Book 3, Ch. 3–5).

## 11. Consent, Privacy & Portability

- Every read/write MUST respect the M02 consent scope (e.g. a coach may read DNA only if sharing was consented).
- For minors, guardian consent (M02) governs access; withdrawal triggers restriction/deletion per Book 3, Ch. 4–5.
- Portability (NFR-M04-04): leaving a tenant removes the tenant's *access*, not the player's profile. The profile follows the person.
- Export/deletion requests are honoured and audited (FR-M04-09).

## 12. Security

- Consent- and RBAC-gated access on all endpoints (M02).
- Profile data encrypted at rest; no PII in logs/URLs.
- Only M16 may write traits; the write path is authenticated and audited.
- All profile mutations recorded to `audit_log` with actor + correlation_id.

## 13. Testing Strategy

- **Unit:** trait update + history append; snapshot generation; baseline computation; consent-scope resolution (typical/boundary/failure).
- **Integration:** M16 writes DNA → history + snapshot correct; M10 reads attributes within latency; leaving a tenant preserves the profile.
- **Contract:** attribute-read and baseline schemas consumed by M10/M15; `dna.updated` event schema.
- **Security (negative):** unconsented coach read denied; non-M16 trait write rejected; cross-tenant access blocked; portability preserved on tenant leave.

## 14. Deployment & Monitoring

- Stateless HA service via standard pipeline; attribute-read path cached for the analysis pipeline.
- Alerts: attribute-read latency, DNA write errors, consent-denied spikes.
- Dashboards: profiles active, DNA update volume, progress-query usage, export/deletion SLA.

## 15. Future Enhancements

- Multi-discipline DNA (bowling/keeping/fielding traits) on the same profile.
- Player-controlled sharing links (grant a scout time-boxed read access).
- Cross-player anonymised aggregates feeding skill-tier benchmarks (M15/CIBL).

## 16. Claude Code Implementation Guide

Depends on M01 and M02 being complete. Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | Schema + migrations (player_profiles, dna_traits, dna_trait_history, dna_snapshots, history_index, personal_baselines) | Migrations apply/rollback; person-anchored, not tenant-owned |
| 2 | Attribute CRUD + fast read for M10 | Attribute read returns <50ms; consent enforced |
| 3 | DNA store: current traits + append-only history + M16 write path | Only M16 can write; history is append-only and reconstructable |
| 4 | DNA snapshots + trend/progress queries | Point-in-time snapshot + period trend return correctly |
| 5 | Personal baseline computation + M15 read API | Baseline served in the CIP-STD metric shape |
| 6 | Consent enforcement, export & deletion, portability | Leaving a tenant preserves profile; export/delete honoured + audited |
| 7 | Events (`profile.updated`, `dna.updated`) + audit | Events emitted; all mutations audited |

## 17. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M04-01 | A profile is bound to the global person and survives leaving/joining tenants unchanged (ENG-002). |
| AC-M04-02 | M10 can read height/stance/age band in <50ms; a non-consented reader is denied. |
| AC-M04-03 | Only M16 can write traits; trait history is append-only and reconstructable to any prior point. |
| AC-M04-04 | A DNA snapshot and a period trend query return correct, versioned data. |
| AC-M04-05 | The personal baseline is served to M15 in the CIP-STD metric shape. |
| AC-M04-06 | Export and deletion requests are honoured; withdrawal of consent restricts access. |
| AC-M04-07 | All profile mutations are audited with actor + correlation_id; `dna.updated` events are emitted. |

## 18. Appendix — Glossary

| Term | Meaning |
|---|---|
| Cricket DNA | The player's persistent, versioned technical trait profile |
| Attribute | An input characteristic (height, stance, age band) used by analysis |
| Trait | An output characteristic (aggression, balance, etc.) computed by M16 |
| Personal baseline | The player's own historical per-metric distribution |
| Snapshot | A point-in-time, versioned copy of the full DNA |
| Portability | Profile follows the person across tenants (ENG-002) |
| History index | Links a player to their sessions/analyses/reports over time |
