# Module M09 — Shot Recognition

**CIP Blueprint · Volume 6 (Module Specifications)**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M09-SHOT |
| Version | 1.0 |
| Status | Draft v1.0 |
| Owner | CIP Labs — Intelligence / Vision |
| Classification | Confidential |
| Date | July 2026 |

**Version History**

| Version | Date | Author | Summary |
|---|---|---|---|
| 0.1 | Jul 2026 | CIP Labs | Outline |
| 1.0 | Jul 2026 | CIP Labs | First complete draft |

**Dependencies (Inputs)**

- Module M01 — Platform Foundation (worker template, event client, storage, audit)
- Module M05 — Video Intelligence (normalised clip + quality)
- Module M06 — Pose Engine (`pose.keypoints`)
- Module M07 — Bat Detection (`bat.tracked`, optional but improves accuracy)
- Module M08 — Ball Tracking (`ball.events`, optional contact context)
- Book 2 — Reference Architecture (Intelligence Plane; pipeline)
- Book 3 — Engineering Standards (testing, AI validation gate, DoD)
- Book 4 — CIP-STD Ch. 5 (Shot entity; phases)

**Feeds Into (Downstream)**

- M10 Biomechanics Engine (shot type selects benchmark ranges & phase model)
- M12/M13 (shot-specific rules), M14 Report, M15 Benchmark; publishes `shot.classified`

---

## Contents

1. Executive Summary
2. Business Context
3. Scope & Responsibilities
4. Personas & Consumers
5. Shot Taxonomy & Phase Segmentation
6. Functional Requirements
7. Non-Functional Requirements
8. Architecture
9. Data & Artefact Design
10. API / Event Specification
11. AI Design & Algorithms
12. Security & Privacy
13. Testing & Validation Strategy
14. Deployment & Monitoring
15. Future Enhancements
16. Claude Code Implementation Guide
17. Acceptance Criteria
18. Appendix — Glossary

---

## 1. Executive Summary

Module M09, Shot Recognition, answers two linked questions about a stroke: *which shot was it?* (cover drive, pull, cut, sweep, defensive, …) and *what were its phases?* (stance, backlift, downswing, impact, follow-through). The shot class is essential context for everything downstream: the Biomechanics Engine (M10) selects the correct benchmark ranges and phase model per shot type, and the Knowledge Graph (M12) applies shot-specific coaching rules. Phase segmentation gives every later metric a temporal structure to attach to.

M09 is back in **Green-tier** territory: cricket shot classification from pose has been demonstrated at high accuracy in peer-reviewed work, so this is a tractable, well-understood learning task. It fuses pose (M06), and where available bat motion (M07) and ball contact (M08), into a robust classification plus a phase timeline.

## 2. Business Context

Shot type is the hinge that makes the rest of the analysis *contextual* rather than generic. Book 1 (Sports Science) stressed that technique must be evaluated in context; a cover drive and a pull have different "correct" ranges for the same metric. Without reliable shot recognition, the platform would apply one-size-fits-all benchmarks and lose credibility with coaches. M09 is therefore a small module with outsized leverage on the trustworthiness of every report.

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Shot classification | Assign a shot class + confidence to the stroke |
| Phase segmentation | Split the stroke into stance/backlift/downswing/impact/follow-through |
| Multi-signal fusion | Combine pose (+ bat, + ball) features for robustness |
| Confidence & abstention | Low-confidence → `unclassified` rather than a wrong label |
| Phase-method reporting | Report whether phases used ball events or bat-only fallback |

### 3.2 Out of scope

- Metric computation (M10), coaching interpretation (M12/M13). M09 provides shot class + phases; others interpret them.

## 4. Personas & Consumers

| Consumer | Need from M09 |
|---|---|
| M10 Biomechanics Engine | Shot type (benchmark selection) + phase boundaries |
| M12/M13 Knowledge/Reasoning | Shot class to apply shot-specific rules |
| M15 Benchmark | Shot-scoped benchmark selection |
| ML/validation | Versioned classifier measurable against the golden dataset |

## 5. Shot Taxonomy & Phase Segmentation

**Shot classes (v1 set):** straight drive, cover drive, on drive, flick, pull, hook, cut, sweep, reverse sweep, lofted shot, defensive stroke. Extensible via CIP-STD (Book 4 Ch. 5).

**Phases:** stance → backlift → downswing → impact → follow-through, per the biomechanics phase model (Book 1 flagship chapter, REQ-BIO-007). Phase boundaries are emitted as frame indices for M10.

| Output | Meaning |
|---|---|
| shot_class | One of the taxonomy (or `unclassified`) |
| shot_confidence | Classification confidence |
| phase_boundaries | Frame indices for the five phases |
| phase_method | `standard` (with ball events) or `bat_only_fallback` |

## 6. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M09-01 | Classify the stroke into the v1 shot taxonomy with a confidence value. |
| FR-M09-02 | Abstain (`unclassified`) when confidence is below threshold rather than emit a likely-wrong label. |
| FR-M09-03 | Segment the stroke into the five phases and emit phase_boundaries as frame indices. |
| FR-M09-04 | Fuse pose (M06) with bat (M07) and ball (M08) features where available; degrade to pose-only. |
| FR-M09-05 | Report `phase_method` (standard vs bat_only_fallback), consistent with M08/M10 fallback behaviour. |
| FR-M09-06 | Publish `shot.classified` (class + confidence + phase_boundaries + phase_method) with correlation_id. |
| FR-M09-07 | Serve a versioned classifier; support canary/rollback (ENG-007). |
| FR-M09-08 | Route consented, low-confidence, or misclassified samples to the annotation pipeline (SHOULD). |

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-M09-01 | Classification MUST fit within the vision/analytics budget (Book 2 Ch. 3). |
| NFR-M09-02 | Every output MUST carry a confidence value; abstention MUST be available. |
| NFR-M09-03 | Processing MUST be idempotent per correlation_id. |
| NFR-M09-04 | Classifier changes MUST pass the golden-dataset validation gate (accuracy + confusion targets) before production (ENG-007). |
| NFR-M09-05 | May run CPU or GPU depending on model; MUST scale on queue depth. |

## 8. Architecture

M09 consumes pose/bat/ball outputs (not raw video) and produces `shot.classified`. It sits after the parallel perception fan-out and before the analytics stages (Book 2 Ch. 3), providing the context M10 needs.

```
pose.keypoints (+ bat.tracked + ball.events) → M09 [ feature build → classify (+abstain) →
   phase segment (standard or bat_only_fallback) ] → shot.classified → M10
```

## 9. Data & Artefact Design

| Store | Holds |
|---|---|
| shot_runs (DB) | id, correlation_id, model_version, shot_class, shot_confidence, phase_boundaries(JSONB), phase_method, created_at |
| annotation_queue | Consented / low-confidence samples for labelling |

Shot output is compact and stored in the DB (no large artefact needed).

## 10. API / Event Specification

| Interface | Purpose |
|---|---|
| (event in) pose.keypoints / bat.tracked / ball.events | Feature inputs |
| (event out) shot.classified | Class + confidence + phases + method |
| GET /v1/shot/{correlationId} | Internal status/summary |
| POST /internal/shot/classify | Internal synchronous entry (tests / reprocessing) |

Event schemas versioned in the registry (Book 2 Ch. 4).

## 11. AI Design & Algorithms

- **Features:** temporal pose sequence (joint trajectories), plus bat-motion and ball-contact features when available — a multi-signal representation that degrades to pose-only.
- **Classifier:** a temporal model (e.g. sequence classifier over pose; the literature shows high accuracy with pose + a classifier). Versioned in the registry.
- **Abstention:** a calibrated confidence threshold; below it, emit `unclassified` so M10 can apply generic handling rather than the wrong shot's benchmarks.
- **Phase segmentation:** the state machine from the biomechanics phase model (REQ-BIO-007), using ball events when present and the bat-only heuristic otherwise (REQ-BIO-008) — the `phase_method` records which was used.

## 12. Security & Privacy

- Consumes already-consented derived artefacts (pose/bat/ball); no new PII.
- Consent-governed annotation capture; minors per Book 0 §11.1.
- No raw frames/PII in logs; only correlation_id, model_version, and outputs.

## 13. Testing & Validation Strategy

- **Unit:** feature construction; abstention thresholding; phase-boundary derivation; method selection (typical/boundary/failure).
- **Integration:** pose(+bat+ball) → `shot.classified`; pose-only degradation works; phase_method matches M08 fallback state.
- **Contract:** `shot.classified` schema consumed by M10/M12/M15.
- **AI validation (release-gating, ENG-007):** classification accuracy AND a confusion-matrix target (no dangerous systematic confusions) MUST be met on the golden dataset; regressions block release (Book 3 Ch. 6).

## 14. Deployment & Monitoring

- CPU/GPU worker autoscaled on queue depth; classifier pinned and canaried (ENG-007).
- Alerts: classification latency, abstention-rate spikes, confidence drift, per-class error drift.
- Dashboards: per-class accuracy vs golden, confusion matrix over time, abstention rate.

## 15. Future Enhancements

- Finer shot sub-types and shot-outcome tags.
- Bowling/keeping/fielding action recognition reusing this temporal-classification pattern (Phase 4 disciplines).
- Perception-action features (feeds the future Cricket Cognition Engine, Book 1 Ch. 4 note).

## 16. Claude Code Implementation Guide

Depends on M06 (and benefits from M07/M08). Requires a labelled shot dataset. Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | Worker scaffold + model-registry integration | Pinned classifier loads/serves; scales on queue depth |
| 2 | Feature builder from pose (+ optional bat/ball) | Feature vectors produced; pose-only path works |
| 3 | Shot classifier + calibrated abstention | Classes + confidence emitted; low-confidence → unclassified |
| 4 | Phase segmentation (standard + bat_only_fallback) | phase_boundaries + phase_method correct |
| 5 | Publish `shot.classified` (idempotent) + annotation routing | Downstream event correct; flywheel active |
| 6 | Wire golden-dataset validation gate (accuracy + confusion) into CI/CD | Classifier change blocked on regression |

## 17. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M09-01 | A stroke is classified into the v1 taxonomy with a confidence value. |
| AC-M09-02 | Below the confidence threshold, M09 emits `unclassified` rather than a likely-wrong label. |
| AC-M09-03 | Phase boundaries are emitted as frame indices for the five phases. |
| AC-M09-04 | `phase_method` reports standard vs bat_only_fallback consistent with M08 state. |
| AC-M09-05 | Classification degrades to pose-only when bat/ball are unavailable. |
| AC-M09-06 | `shot.classified` is published with correct schema and correlation_id; re-delivery is idempotent. |
| AC-M09-07 | A classifier change that regresses accuracy or confusion targets is blocked by the validation gate (ENG-007). |

## 18. Appendix — Glossary

| Term | Meaning |
|---|---|
| Shot class | The recognised stroke type |
| Phase | A temporal segment of the stroke |
| Abstention | Emitting `unclassified` when confidence is low |
| phase_method | Whether phases used ball events or bat-only fallback |
| Confusion target | Bound on dangerous systematic misclassifications |
| shot.classified | The event M09 publishes to downstream modules |
