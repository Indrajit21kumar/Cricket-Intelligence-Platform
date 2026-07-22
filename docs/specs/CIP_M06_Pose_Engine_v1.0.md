# Module M06 — Pose Engine

**CIP Blueprint · Volume 6 (Module Specifications)**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M06-POSE |
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

- Module M01 — Platform Foundation (event client, GPU worker template, storage, audit)
- Module M05 — Video Intelligence (`video.normalized` + calibration + quality flags)
- Book 2 — Reference Architecture (Intelligence Plane; pipeline; GPU pools; <60s SLA)
- Book 3 — Engineering Standards (testing, AI validation gate, MLOps, DoD)
- Book 4 — CIP-STD Ch. 2 (coordinate frame, confidence conventions)

**Feeds Into (Downstream)**

- M09 Shot Recognition, M10 Biomechanics Engine (primary consumer)
- Publishes `pose.keypoints` to the event bus

---

## Contents

1. Executive Summary
2. Business Context
3. Scope & Responsibilities
4. Personas & Consumers
5. Keypoint Schema & Model Strategy
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

Module M06, the Pose Engine, is the platform's shared "eyes." It takes a normalised clip from M05 and produces, for every frame, a set of body keypoints (joints) with a confidence value each. This per-frame skeleton is the raw material from which the Biomechanics Engine (M10) computes angles, timing, and positions, and from which Shot Recognition (M09) classifies strokes. Pose is an *input* to the platform's intelligence, never the output shown to a user (a core principle from Books 0 and 1: "computer vision is the sensor, not the coach").

M06 is deliberately a thin, well-validated, GPU-served component with one job done reliably: accurate, confidence-scored keypoints in the CIP coordinate conventions, with primary-subject tracking so exactly one batter is followed even when other people are in frame.

## 2. Business Context

Pose estimation is the most mature, lowest-risk part of the vision stack (feasibility study: "Green tier"). Off-the-shelf models (MediaPipe, MoveNet, ViTPose) are production-grade. M06's value is not novel research; it is disciplined engineering — selecting the right model, tracking the correct subject, enforcing confidence gating, and emitting keypoints in the exact schema and frame the rest of the platform expects. Getting M06 right and boring is what lets the differentiated modules (physics, knowledge, benchmarking) be built on solid ground.

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Keypoint extraction | Per-frame body keypoints + per-joint confidence |
| Primary-subject tracking | Follow exactly one batter across frames; resolve multi-person frames |
| Confidence gating | Aggregate confidence; mark low-confidence sequences provisional |
| Coordinate normalisation | Emit keypoints consistent with the CIP frame (Book 4 Ch. 2) |
| Model serving | GPU inference with autoscaling and a versioned model |

### 3.2 Out of scope

- Bat/ball detection (M07/M08), biomechanical interpretation (M10), and 3D lifting quality research (tracked as a research item; M06 exposes 2D keypoints + optional estimated depth flag).

## 4. Personas & Consumers

| Consumer | Need from M06 |
|---|---|
| M10 Biomechanics Engine | Reliable per-frame keypoints + confidence in the CIP frame |
| M09 Shot Recognition | Pose sequence as classifier features |
| Platform/SRE | Predictable GPU cost and latency; observable model health |
| ML/validation | Versioned model measurable against the golden dataset |

## 5. Keypoint Schema & Model Strategy

M06 emits a stable keypoint schema (a superset covering head, neck, shoulders, elbows, wrists, hips, knees, ankles — with hand/foot keypoints where the chosen model supports them). Each keypoint carries `(x, y, confidence)` and, where depth is estimated, `z` plus `depth_estimated = true`.

| Aspect | Standard |
|---|---|
| Body keypoints | Canonical joint set (min 17; extended set where model allows) |
| Per-joint output | x, y, confidence (+ optional z with depth_estimated) |
| Frame reference | CIP normalised frame conventions (Book 4 Ch. 2) |
| Model | Pluggable (MediaPipe / MoveNet / ViTPose); versioned in the registry |
| Handedness | Raw output; mirroring is applied downstream (M10) per Book 4 |

Model choice is an implementation decision constrained by the validation gate (Section 13); the schema is fixed so downstream modules are model-agnostic.

## 6. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M06-01 | Consume `video.normalized` and produce per-frame keypoints with per-joint confidence. |
| FR-M06-02 | Perform primary-subject tracking: follow exactly one batter across the clip. |
| FR-M06-03 | Reject/flag clips with >1 unresolved subject (`MULTI_SUBJECT_AMBIGUOUS`) rather than guess. |
| FR-M06-04 | Emit keypoints in the CIP coordinate conventions (Book 4 Ch. 2); carry `depth_estimated` where z is inferred. |
| FR-M06-05 | Aggregate per-frame confidence; if the confidence gate (per Book 4 / M10 contract) is not met, mark output provisional. |
| FR-M06-06 | Publish `pose.keypoints` (artefact reference + summary + quality) with correlation_id. |
| FR-M06-07 | Serve a versioned model; support canary rollout and rollback (ENG-007). |
| FR-M06-08 | Propagate M05 quality flags and calibration references through the output envelope. |
| FR-M06-09 | Persist the keypoint artefact to object storage linked by correlation_id. |

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-M06-01 | Pose extraction MUST fit within the vision stage budget (part of 20–40s; Book 2 Ch. 3). |
| NFR-M06-02 | GPU workers MUST autoscale on queue depth and scale to zero when idle (Book 3 Ch. 7). |
| NFR-M06-03 | Every keypoint MUST carry a confidence value; no silent gap-filling without a flag. |
| NFR-M06-04 | Processing MUST be idempotent per correlation_id. |
| NFR-M06-05 | Model changes MUST pass the golden-dataset validation gate before production (ENG-007). |

## 8. Architecture

M06 is a GPU-served **Intelligence-Plane** service. It subscribes to `video.normalized`, runs the pose model on extracted frames, applies primary-subject tracking and confidence aggregation, and publishes `pose.keypoints`. It runs in parallel with M07 (bat) and M08 (ball) on the same normalised clip (Book 2, Ch. 3 fan-out).

```
video.normalized → M06 [ load frames → pose model (GPU) → primary-subject track →
   confidence aggregate → normalise to CIP frame ] → pose.keypoints (artefact + summary)
                                            (parallel with M07 bat, M08 ball)
```

## 9. Data & Artefact Design

Keypoint sequences are large and are stored as artefacts in object storage, with a compact summary in the database.

| Store | Holds |
|---|---|
| Object storage | Full per-frame keypoint sequence (artefact), referenced by correlation_id |
| pose_runs (DB) | id, correlation_id, model_version, frame_count, mean_confidence, subject_status, quality, created_at |

The DB row is the queryable index; the heavy keypoint payload stays in object storage (consistent with M05's artefact pattern).

## 10. API / Event Specification

| Interface | Purpose |
|---|---|
| (event in) video.normalized | Trigger: normalised clip + calibration + quality |
| (event out) pose.keypoints | Artefact ref + summary (mean confidence, subject_status, quality) |
| GET /v1/pose/{correlationId} | Internal status/summary for debugging & orchestration |
| POST /internal/pose/compute | Internal synchronous entry (used in tests / reprocessing) |

Event schemas are versioned in the schema registry (Book 2, Ch. 4).

## 11. AI Design & Algorithms

- **Model:** a pluggable pose estimator (MediaPipe / MoveNet / ViTPose), selected to meet the validation gate; served from the model registry with a pinned version.
- **Primary-subject tracking:** select and track the batter across frames (e.g. by position/continuity heuristics); on unresolved multi-subject frames, fail per FR-M06-03 rather than emit ambiguous keypoints.
- **Confidence handling:** aggregate per-joint confidences to a per-frame and per-clip mean; the low-confidence policy (provisional output) matches the Biomechanics Engine input contract (see the earlier Biomechanics Engine chapter, REQ-BIO-003).
- **Depth:** if a monocular 3D-lifting model is used, mark all depth-derived values `depth_estimated`; 2D remains the reliable baseline (feasibility "Amber" note).

## 12. Security & Privacy

- Operates on already-consented, tenant/player-namespaced video (M02/M05); no new PII collected.
- Keypoint artefacts are personal data: encrypted at rest, access-controlled, retention/deletion per Book 3 Ch. 4–5.
- No frames or identifiable imagery in logs; only correlation_id, model_version, and quality summaries.

## 13. Testing & Validation Strategy

- **Unit:** confidence aggregation; subject-tracking selection; coordinate normalisation; multi-subject rejection (typical/boundary/failure).
- **Integration:** `video.normalized` → `pose.keypoints` with correct schema and quality propagation; parallel execution with M07/M08.
- **Contract:** `pose.keypoints` schema consumed by M09/M10.
- **AI validation (release-gating, ENG-007):** keypoint accuracy MUST meet the tolerance defined against the golden dataset (mocap-derived ground truth); a model change that regresses accuracy beyond tolerance MUST NOT ship (Book 3 Ch. 6).
- **Regression:** snapshot outputs for a fixed reference clip set on every model change.

## 14. Deployment & Monitoring

- GPU worker pool, autoscaled on queue depth, scale-to-zero when idle; model pinned and canaried (Book 3 Ch. 7; ENG-007).
- Alerts: pose stage latency, GPU utilisation/queue depth, mean-confidence drift, multi-subject rejection rate.
- Model dashboards: confidence distribution and accuracy-vs-golden over time (drift).

## 15. Future Enhancements

- Cricket-specific fine-tuned pose head for occluded/helmeted cases.
- Improved monocular 3D lifting to reduce depth error (feeds Book 1 Ch. 11 research; would raise positional-metric confidence).
- Whole-body (hand/foot) keypoints to unlock foot-alignment metrics (BM-07) reliably.

## 16. Claude Code Implementation Guide

Depends on M01 and M05. Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | GPU worker scaffold (from M01 template) + model registry integration | A pinned model loads and serves on GPU; scales to zero when idle |
| 2 | Consume `video.normalized`; run pose over frames | Per-frame keypoints + confidence produced |
| 3 | Primary-subject tracking + multi-subject rejection | Single batter tracked; ambiguous frames rejected (FR-M06-03) |
| 4 | Coordinate normalisation + depth_estimated flagging | Output matches CIP frame (Book 4 Ch. 2) |
| 5 | Confidence aggregation + provisional-output policy | Low-confidence clips flagged provisional per M10 contract |
| 6 | Persist artefact + publish `pose.keypoints` (idempotent) | Downstream event correct; re-delivery safe |
| 7 | Wire golden-dataset validation gate into CI/CD | Model change blocked if accuracy regresses beyond tolerance |

## 17. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M06-01 | Given a `video.normalized`, M06 emits per-frame keypoints with per-joint confidence in the CIP frame. |
| AC-M06-02 | Exactly one batter is tracked; a multi-subject clip is rejected with `MULTI_SUBJECT_AMBIGUOUS`, not guessed. |
| AC-M06-03 | Depth-derived values (if any) carry `depth_estimated`; 2D keypoints are always present. |
| AC-M06-04 | Low-confidence input yields a `provisional` output consistent with the M10 input contract. |
| AC-M06-05 | `pose.keypoints` is published with correct schema, quality summary, and correlation_id; re-delivery is idempotent. |
| AC-M06-06 | A model change that regresses keypoint accuracy beyond tolerance is blocked by the validation gate (ENG-007). |
| AC-M06-07 | GPU workers autoscale on queue depth and scale to zero when idle. |

## 18. Appendix — Glossary

| Term | Meaning |
|---|---|
| Keypoint | A detected body joint with (x, y, confidence) |
| Primary-subject tracking | Following the one batter across frames |
| Confidence gate | Threshold below which output is marked provisional |
| depth_estimated | Flag that a z value is inferred from monocular video |
| Golden dataset | Ground-truth set for release-gating model accuracy |
| Artefact | Large output (keypoint sequence) stored in object storage |
| pose.keypoints | The event M06 publishes to downstream engines |
