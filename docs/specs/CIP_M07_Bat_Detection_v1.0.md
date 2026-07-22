# Module M07 — Bat Detection

**CIP Blueprint · Volume 6 (Module Specifications)**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M07-BAT |
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

- Module M01 — Platform Foundation (GPU worker template, event client, storage, audit)
- Module M05 — Video Intelligence (`video.normalized` + calibration + quality flags)
- Module M06 — Pose Engine (player keypoints, for hand/bat association)
- Book 2 — Reference Architecture (Intelligence Plane; pipeline; GPU pools)
- Book 3 — Engineering Standards (data, testing, AI validation gate, MLOps, DoD)
- Book 4 — CIP-STD Ch. 2–3 (coordinate frame; bat-dependent metrics BM-09..BM-13)

**Feeds Into (Downstream)**

- M10 Biomechanics Engine (bat path, backlift, bat lag, follow-through)
- M09 Shot Recognition (bat motion as a feature); publishes `bat.tracked`

---

## Contents

1. Executive Summary
2. Business Context (and the Amber-tier reality)
3. Scope & Responsibilities
4. Personas & Consumers
5. Detection Targets & Output Schema
6. Functional Requirements
7. Non-Functional Requirements
8. Architecture
9. Data, Artefact & Training-Data Design
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

Module M07, Bat Detection, locates and tracks the cricket bat through every frame of a stroke — the handle, blade, and sweet-spot region — and derives the bat's angle and swing plane. This is the input the Biomechanics Engine (M10) needs for the bat-dependent metrics: backlift (BM-09), bat path (BM-10), bat lag (BM-11), and follow-through (BM-13). Where M06 answers "where is the body," M07 answers "where is the bat."

Unlike pose estimation, bat detection is not solved off the shelf — no general model knows what a cricket bat is or how it moves. M07 therefore depends on a **custom-trained detector** and, consequently, on CIP's own labelled cricket dataset. This makes M07 the first module whose quality is gated as much by data as by code.

## 2. Business Context (and the Amber-tier reality)

The feasibility study classified bat tracking as "Amber": buildable, but requiring a proprietary labelled dataset and careful handling of failure cases (motion blur during a fast backlift, occlusion by the body). M07 is where the platform begins converting user uploads into a data moat — every consented clip is potential training data (Book 1, data strategy). The honest consequence, reflected throughout this spec: M07 ships with explicit confidence and graceful degradation, and its bat-dependent metrics are marked **provisional** when detection is unreliable, rather than presenting false precision (Book 0 §8).

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Bat detection | Locate the bat per frame (bounding region + key parts) |
| Part localisation | Handle, blade, sweet-spot region |
| Bat pose | Bat angle and swing-plane derivation per frame |
| Tracking | Temporal tracking of the bat across the stroke |
| Hand–bat association | Use M06 wrist keypoints to disambiguate the batter's bat |
| Confidence & degradation | Per-frame confidence; provisional flag when unreliable |
| Training-data capture | Emit consented frames/labels into the annotation pipeline |

### 3.2 Out of scope

- Biomechanical interpretation of bat motion (M10), ball tracking (M08), and shot classification (M09). M07 provides bat geometry; others interpret it.

## 4. Personas & Consumers

| Consumer | Need from M07 |
|---|---|
| M10 Biomechanics Engine | Per-frame bat keypoints/angle for BM-09..BM-13 |
| M09 Shot Recognition | Bat motion as a classifier feature |
| Data/annotation team | Consented frames routed for labelling (dataset growth) |
| ML/validation | Versioned detector measurable against the golden dataset |

## 5. Detection Targets & Output Schema

Per frame, M07 emits bat keypoints with confidence and a derived bat pose.

| Output | Meaning |
|---|---|
| handle_top / handle_bottom | Ends of the handle (x, y, confidence) |
| blade_tip | Toe of the blade (x, y, confidence) |
| sweet_spot | Estimated sweet-spot region centre (x, y, confidence) |
| bat_angle | Bat orientation vs vertical in the CIP frame (deg) |
| swing_plane | Derived plane of the swing across frames |
| detection_confidence | Per-frame bat-detection confidence |

Output uses the CIP coordinate conventions (Book 4 Ch. 2). Sweet-spot and swing-plane are derived (lower-confidence) quantities and labelled accordingly.

## 6. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M07-01 | Consume `video.normalized` and detect the bat per frame (region + parts). |
| FR-M07-02 | Localise handle_top, handle_bottom, blade_tip, and estimate the sweet-spot region. |
| FR-M07-03 | Derive bat_angle (CIP frame) and swing_plane across the stroke. |
| FR-M07-04 | Track the bat temporally; use M06 wrist keypoints to associate the correct bat with the batter. |
| FR-M07-05 | Emit per-frame detection_confidence; when detection fails on >30% of downswing frames, mark bat-dependent output provisional (matches M10 contract). |
| FR-M07-06 | Publish `bat.tracked` (artefact ref + summary + quality) with correlation_id. |
| FR-M07-07 | Serve a versioned, custom-trained detector; support canary rollout and rollback (ENG-007). |
| FR-M07-08 | Route consented frames/labels to the annotation pipeline for dataset growth (SHOULD). |
| FR-M07-09 | Persist the bat-track artefact to object storage linked by correlation_id. |

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-M07-01 | Bat detection MUST fit within the vision stage budget (part of 20–40s; runs parallel to M06/M08). |
| NFR-M07-02 | GPU workers MUST autoscale on queue depth and scale to zero when idle. |
| NFR-M07-03 | Every bat output MUST carry confidence; derived quantities (sweet-spot, swing-plane) MUST be labelled as derived. |
| NFR-M07-04 | Processing MUST be idempotent per correlation_id. |
| NFR-M07-05 | Detector changes MUST pass the golden-dataset validation gate (bat-detection accuracy target) before production (ENG-007). |

## 8. Architecture

M07 is a GPU-served **Intelligence-Plane** service running in parallel with M06 (pose) and M08 (ball) on the same normalised clip. It reads M06 wrist keypoints to disambiguate the batter's bat, runs the custom detector + tracker, derives bat pose, and publishes `bat.tracked`.

```
video.normalized ─┬→ M06 pose ─┐
                  ├→ M07 bat  ─┤ (uses M06 wrists for hand–bat association)
                  └→ M08 ball ─┘
M07: detect → part-localise → track → derive angle/plane → confidence/degradation → bat.tracked
```

## 9. Data, Artefact & Training-Data Design

| Store | Holds |
|---|---|
| Object storage | Per-frame bat-keypoint sequence (artefact), referenced by correlation_id |
| bat_runs (DB) | id, correlation_id, model_version, frames_detected, mean_confidence, provisional, quality, created_at |
| annotation_queue | Consented frames + weak labels routed for human labelling (dataset growth) |

M07 is the first module where the **training-data flywheel** is explicit: consented, low-confidence, or sampled frames are routed to `annotation_queue`, labelled, and fed back to improve the detector (Book 1 data strategy; Book 3 MLOps).

## 10. API / Event Specification

| Interface | Purpose |
|---|---|
| (event in) video.normalized | Trigger: normalised clip + calibration |
| (event in) pose.keypoints | M06 wrists for hand–bat association |
| (event out) bat.tracked | Artefact ref + summary (mean confidence, provisional, quality) |
| GET /v1/bat/{correlationId} | Internal status/summary |
| POST /internal/bat/compute | Internal synchronous entry (tests / reprocessing) |

Event schemas versioned in the schema registry (Book 2 Ch. 4).

## 11. AI Design & Algorithms

- **Detector:** a custom-trained object/keypoint model (e.g. a YOLO-family or keypoint detector fine-tuned on cricket-bat data); served from the model registry, versioned.
- **Tracking:** temporal association of the bat across frames; smoothing consistent with the biomechanics filtering approach (avoid jitter-inflated angles).
- **Hand–bat association:** use M06 wrist keypoints to select the batter's bat when multiple bat-like objects appear.
- **Failure modes handled explicitly:** motion blur during fast backlift and occlusion by the body reduce confidence; the >30%-downswing-failure rule (FR-M07-05) drives the provisional flag that M10 honours.
- **Derived quantities:** sweet-spot and swing-plane are modelled from detected parts and labelled lower-confidence.

## 12. Security & Privacy

- Operates on consented, tenant/player-namespaced video (M02/M05); artefacts encrypted at rest.
- Training-data capture is strictly consent-governed; only consented frames enter `annotation_queue`; minors' data handled per Book 0 §11.1.
- No frames/PII in logs; only correlation_id, model_version, and quality summaries.

## 13. Testing & Validation Strategy

- **Unit:** part-localisation geometry; bat-angle derivation (CIP frame); hand–bat association; degradation rule (typical/boundary/failure).
- **Integration:** parallel run with M06/M08; `bat.tracked` emitted with correct schema and provisional flag when detection is poor.
- **Contract:** `bat.tracked` schema consumed by M10/M09.
- **AI validation (release-gating, ENG-007):** bat-detection accuracy MUST meet its target on the golden dataset; regressions block release (Book 3 Ch. 6).
- **Robustness:** curated hard cases (blur, occlusion, multiple bats in frame) MUST behave per the degradation policy.

## 14. Deployment & Monitoring

- GPU pool, autoscaled, scale-to-zero; detector pinned and canaried (ENG-007).
- Alerts: bat-stage latency, detection-confidence drift, provisional-rate spikes, annotation-queue backlog.
- Dashboards: detection rate by camera angle, mean confidence over time, dataset growth from annotation.

## 15. Future Enhancements

- Bat-face orientation estimation (feeds Physics PH-10 impact-quality, still ESTIMATED).
- Active-learning selection of the most informative frames for labelling.
- Sensor-fusion option (smart-bat IMU) for validation of vision-derived bat metrics.

## 16. Claude Code Implementation Guide

Depends on M01, M05, M06. Requires an initial labelled cricket-bat dataset before the detector can be trained/validated. Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | GPU worker scaffold + model-registry integration | A pinned detector loads/serves on GPU; scales to zero |
| 2 | Bootstrap annotation pipeline + initial labelled set | A labelled bat dataset exists and is versioned |
| 3 | Train/serve custom bat detector (parts) | Detector localises handle/blade/sweet-spot on validation clips |
| 4 | Temporal tracking + hand–bat association (uses M06 wrists) | Correct bat tracked across the stroke |
| 5 | Bat-angle + swing-plane derivation (CIP frame) | Angles emitted in Book 4 Ch. 2 conventions |
| 6 | Confidence + degradation policy (>30% downswing rule) | Poor detection yields provisional output per M10 contract |
| 7 | Publish `bat.tracked` (idempotent) + route consented frames to annotation | Event correct; dataset flywheel active |
| 8 | Wire golden-dataset validation gate into CI/CD | Detector change blocked if accuracy regresses beyond target |

## 17. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M07-01 | Given a `video.normalized`, M07 emits per-frame bat keypoints (handle/blade/sweet-spot) + bat_angle in the CIP frame. |
| AC-M07-02 | The batter's bat is correctly associated using M06 wrist keypoints when multiple bat-like objects appear. |
| AC-M07-03 | When detection fails on >30% of downswing frames, output is marked provisional consistent with the M10 contract. |
| AC-M07-04 | Derived quantities (sweet-spot, swing-plane) are labelled as derived/lower-confidence. |
| AC-M07-05 | `bat.tracked` is published with correct schema, quality summary, and correlation_id; re-delivery is idempotent. |
| AC-M07-06 | A detector change that regresses bat-detection accuracy beyond target is blocked by the validation gate (ENG-007). |
| AC-M07-07 | Only consented frames enter the annotation queue; minors' data is handled per policy. |

## 18. Appendix — Glossary

| Term | Meaning |
|---|---|
| Bat keypoints | handle_top, handle_bottom, blade_tip, sweet_spot |
| Bat angle | Bat orientation vs vertical in the CIP frame |
| Swing plane | Derived plane of the bat's motion across frames |
| Provisional | Reduced-confidence output flag honoured by M10 |
| Annotation queue | Consented frames routed for labelling (dataset growth) |
| Amber tier | Buildable but data-dependent, with graceful degradation |
| bat.tracked | The event M07 publishes to downstream modules |
