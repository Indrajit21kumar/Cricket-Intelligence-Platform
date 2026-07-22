# Module M10 — Biomechanics Engine

**CIP Blueprint · Volume 6 (Module Specifications) · Flagship analytical module**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M10-BIO |
| Version | 1.0 |
| Status | Draft v1.0 |
| Owner | CIP Labs — Intelligence / Biomechanics |
| Classification | Confidential |
| Date | July 2026 |

**Version History**

| Version | Date | Author | Summary |
|---|---|---|---|
| 0.1 | Jul 2026 | CIP Labs | Outline |
| 1.0 | Jul 2026 | CIP Labs | First complete draft (formalises the Book 1 flagship chapter) |

**Dependencies (Inputs)**

- Module M01 — Platform Foundation (event client, storage, audit)
- Module M04 — Player Profile (anthropometrics: height, stance, age band)
- Module M05 — Video Intelligence (calibration, fps, quality)
- Module M06 — Pose Engine (`pose.keypoints`)
- Module M07 — Bat Detection (`bat.tracked`)
- Module M08 — Ball Tracking (`ball.events`)
- Module M09 — Shot Recognition (`shot.classified`: type + phases)
- Book 4 — CIP-STD Ch. 2–3 (coordinate frame; metric catalogue BM-01..BM-17)

**Feeds Into (Downstream)**

- M11 Physics Engine (sole input), M15 Benchmark, M12/M13 (facts), M14 Report, M16 DNA
- Publishes `biomechanics.metrics`

---

## Contents

1. Executive Summary
2. Business Context
3. Scope & Responsibilities
4. Inputs & Preconditions
5. Coordinate System & Calibration
6. Temporal Segmentation (Phases)
7. Metric Catalogue & Formulas (BM-01..BM-17)
8. Output Data Contract
9. Functional Requirements
10. Non-Functional Requirements & Tolerances
11. Architecture & Relationship to the Physics Engine
12. Database Design
13. API / Event Specification
14. Error Handling & Graceful Degradation
15. Testing & Validation Strategy
16. Security & Privacy
17. Deployment & Monitoring
18. Claude Code Implementation Guide
19. Acceptance Criteria
20. Appendix — Glossary

---

## 1. Executive Summary

Module M10, the Biomechanics Engine, converts the perception layer's outputs — pose, bat, ball, and shot/phase — into the platform's canonical biomechanical metrics: the seventeen CIP-STD measures (BM-01..BM-17) describing a single batting stroke from stance to follow-through. It is the point where raw movement becomes measurable performance variables, and it is the sole input to the Physics Engine (M11) and a primary fact source for the Knowledge Graph (M12), Benchmark Intelligence (M15), and the Report Generator (M14).

M10 is pure numerical computation (CPU): it does not run models or touch raw video. This makes it fast, deterministic, and testable against hand-computed fixtures and against a mocap-derived golden dataset. It is the flagship analytical module because its correctness and honesty (measured values, confidence, graceful degradation) underpin every downstream claim the platform makes.

## 2. Business Context

Book 1 established the platform's founding distinction: understand movement, do not merely detect it. M10 is where that distinction becomes concrete — pose keypoints (detection) become head stability, hip–shoulder separation, bat lag, and timing (understanding). The rigour of M10 (defined coordinate frame, per-metric formulas, tolerance bands validated against motion capture) is what allows CIP to make credible, honest biomechanical claims to coaches, academies, and boards — the trust that differentiates it from pose-detection apps.

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Metric computation | The 17 CIP-STD measured metrics (BM-01..BM-17) per stroke |
| Coordinate normalisation | Compute in the CIP handedness-invariant frame |
| Phase-aware analysis | Use M09 phase boundaries for every phase-relative metric |
| Confidence & provenance | Every metric labelled MEASURED with spatial/depth confidence |
| Graceful degradation | Provisional output when inputs are low-confidence |
| Range validation | Flag out-of-expected-range values for review (not reject) |

### 3.2 Out of scope

- Physics (force/energy — M11), coaching interpretation (M12/M13), benchmarking (M15). M10 measures; others interpret. Bat-face-orientation and any force quantity are explicitly M11's ESTIMATED domain.

## 4. Inputs & Preconditions

| Input | Source | Required fields |
|---|---|---|
| Pose sequence | M06 | keypoints/frame (x,y,[z],confidence), frame_id, timestamp |
| Bat keypoints | M07 | handle_top/bottom, blade_tip, sweet_spot per frame |
| Ball events | M08 | release/bounce/contact frames, timing_reference |
| Shot + phases | M09 | shot_class, phase_boundaries, phase_method |
| Calibration | M05 | pixel_to_meter, camera_angle, fps, spatial_confidence |
| Anthropometrics | M04 | height_cm, stance, age_band |

**Precondition (from the flagship chapter, REQ-BIO-003):** if fewer than 80% of frames in the stroke window have mean keypoint confidence ≥ 0.5, M10 emits `LOW_CONFIDENCE_INPUT` and marks output `provisional: true`.

## 5. Coordinate System & Calibration

M10 computes in the CIP normalised, handedness-invariant batting frame (Book 4 Ch. 2): origin at the ground point beneath mid-stance; X along the crease (positive off-side for the normalised right-hand frame, mirrored for LHB); Y vertical; Z down the pitch toward the bowler. Pixel-to-metric scale comes from M05 calibration; every positional metric carries `spatial_confidence`, and depth-dependent values carry `depth_estimated` (widening tolerance).

## 6. Temporal Segmentation (Phases)

M10 uses the phase boundaries from M09 (stance, backlift, downswing, impact, follow-through; REQ-BIO-007). When ball confidence is low, M09 supplies `phase_method = bat_only_fallback` (REQ-BIO-008), and M10 records this in its output so downstream consumers know the timing basis.

## 7. Metric Catalogue & Formulas (BM-01..BM-17)

All formulas operate in the CIP frame; all outputs are MEASURED (BM-15 is a labelled estimated proxy). Representative formulas below; full definitions in Book 4 Ch. 3.

| ID | Metric | Formula / definition (summary) | Unit |
|---|---|---|---|
| BM-01 | Head stability | `sqrt((X_impact−X_stance)² + (Z_impact−Z_stance)²)·100` | cm |
| BM-02 | Shoulder rotation | Δ of `atan2(Z_R−Z_L, X_R−X_L)` shoulders, stance→impact | deg |
| BM-03 | Hip rotation | Same as BM-02 on hip keypoints | deg |
| BM-04 | X-Factor | `shoulder_rotation − hip_rotation` at downswing start | deg |
| BM-05 | Pelvic tilt | Hip-line angle vs horizontal at impact | deg |
| BM-06 | Front knee flexion | `arccos((v1·v2)/(|v1||v2|))`, v1=knee−hip, v2=knee−ankle | deg |
| BM-07 | Foot alignment | Angle(front-foot axis, crease line) | deg |
| BM-08 | Stride length | `stride_cm / height_cm · 100` | % |
| BM-09 | Backlift | Peak bat angle vs vertical in backlift phase | deg |
| BM-10 | Bat path linearity | R² of best-fit line through downswing sweet-spot path | ratio |
| BM-11 | Bat lag | `θ_bat − θ_forearm` (peak + at 40% downswing) | deg |
| BM-12 | Hand speed | Smoothed derivative of wrist-midpoint (Savitzky-Golay w=5,p=2) | m/s |
| BM-13 | Follow-through | Bat angle/hand height at follow-through end vs stance | deg |
| BM-14 | Balance recovery | Time from impact until CoM horiz. velocity < 0.1 m/s | ms |
| BM-15 | Weight transfer (proxy) | f(Δ front-knee flex, Δ back-knee flex) — **estimated proxy** | ratio |
| BM-16 | Centre of mass | Weighted segment sum (Dempster fractions), projected X-Z | cm path |
| BM-17 | Ground contact timing | `(plant_frame − release_frame)/fps·1000` (or absolute) | ms |

**Filtering rule (REQ-BIO-021):** velocity-derived metrics (BM-12) MUST apply Savitzky-Golay smoothing before differentiation — raw finite-difference overstates peak speed 15–30% due to keypoint jitter.

## 8. Output Data Contract

M10 emits one `BiomechanicsReport` per stroke: `stroke_id`, `shot_type` (+confidence), `phase_boundaries`, the `metrics` object (BM-01..BM-17), and a `quality` block (`mean_pose_confidence`, `spatial_confidence`, `depth_estimated`, `phase_segmentation_method`, `provisional`, `flags`), plus `schema_version` and `computed_at`. Every metric dependent on estimated data (BM-15, depth-dependent, BM-16) carries a `_confidence` companion (REQ-BIO-028).

## 9. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M10-01 | Consume pose/bat/ball/shot + calibration + anthropometrics and compute BM-01..BM-17 per stroke. |
| FR-M10-02 | Compute all positional metrics in the CIP handedness-invariant frame (Book 4 Ch. 2). |
| FR-M10-03 | Use M09 phase boundaries; record `phase_segmentation_method`. |
| FR-M10-04 | Apply the Savitzky-Golay filter before differentiating velocity metrics. |
| FR-M10-05 | Enforce the ≥80%/≥0.5 confidence precondition; else emit `LOW_CONFIDENCE_INPUT` + `provisional`. |
| FR-M10-06 | Mark bat-dependent metrics (BM-09..BM-13) provisional when M07 signals >30% downswing detection failure. |
| FR-M10-07 | Label every metric MEASURED (BM-15 estimated proxy); attach `_confidence` where dependent on estimated data. |
| FR-M10-08 | Flag out-of-expected-range values (`out_of_expected_range`) and route a sample to human review — do NOT reject. |
| FR-M10-09 | Publish `biomechanics.metrics` (BiomechanicsReport) with correlation_id; persist the report. |
| FR-M10-10 | Provide the report as the sole biomechanical input to M11 (no re-derivation downstream). |

## 10. Non-Functional Requirements & Tolerances

| ID | Requirement |
|---|---|
| NFR-M10-01 | Pure CPU numerical compute; complete in ≤3s per stroke (Book 2 Ch. 3 budget). |
| NFR-M10-02 | Sustain ≥50 strokes/s aggregate at P95 <3s under autoscaling. |
| NFR-M10-03 | Deterministic: identical input → identical output (enables snapshot tests). |
| NFR-M10-04 | Idempotent per stroke_id/correlation_id. |

**Accuracy tolerance bands (release-gating vs mocap golden dataset, REQ-BIO-031):**

| Metric class | Tolerance |
|---|---|
| Angular (rotation, flexion, tilt) | ± 5° |
| Timing (ground contact, balance recovery) | ± 2 frames (≈17–33 ms) |
| Linear/positional (head stability, stride) | ± 3 cm (high spatial_confidence only) |
| Velocity-derived (hand speed) | ± 10% |

A pipeline/algorithm change MUST NOT ship if it regresses mean absolute error beyond these bands (ENG-007; Book 3 Ch. 6).

## 11. Architecture & Relationship to the Physics Engine

M10 is a stateless, CPU-bound **Intelligence-Plane** service. It consumes the fan-in of perception events and produces `biomechanics.metrics`.

```
pose.keypoints + bat.tracked + ball.events + shot.classified + calibration + anthropometrics
      → M10 [ normalise → phase-align → compute BM-01..BM-17 → confidence/flags ]
      → biomechanics.metrics → M11 Physics (sole input) / M15 / M12,M13 / M14 / M16
```

**Boundary (REQ-BIO-029):** M11 consumes the BiomechanicsReport and MUST NOT re-derive kinematics from raw pose. This keeps physics a pure function of M10 output + anthropometrics, so M11 tests run on fixture reports without video/pose.

## 12. Database Design

| Table | Key columns | Notes |
|---|---|---|
| biomechanics_reports | id, stroke_id, session_id, player_id, shot_type, shot_confidence, phase_boundaries(JSONB), metrics(JSONB), quality(JSONB), schema_version, out_of_expected_range, reviewed_by_human, computed_at | One report per stroke |

Indexes: `(player_id, computed_at DESC)`; partial index on `out_of_expected_range WHERE NOT reviewed_by_human` (review queue); GIN on `metrics`. Tenant/consent scoping via M02/M04 access layer.

## 13. API / Event Specification

| Interface | Purpose |
|---|---|
| (event in) biomechanics inputs | pose/bat/ball/shot fan-in |
| (event out) biomechanics.metrics | The BiomechanicsReport |
| POST /internal/v1/biomechanics/compute | Synchronous compute (tests/reprocessing); returns report, 202 provisional, or 422 |
| GET /v1/biomechanics/{strokeId} | Report retrieval (auth + consent scoped) |

## 14. Error Handling & Graceful Degradation

| Case | Handling |
|---|---|
| >1 unresolved subject | Rejected upstream (M06); M10 refuses ambiguous input |
| Non-standard camera angle | `spatial_confidence: low`; disable X-axis-dependent metrics (BM-07, BM-08); flag re-film |
| Bat undetected >30% downswing | BM-09..BM-13 `provisional`; score with adjusted weighting |
| No ball data (solo/net) | BM-17 uses absolute timing; `timing_reference: absolute` |
| Left-handed batter | Computed raw then mirrored to the normalised frame before storage |
| Out-of-range value | Flagged + sampled to review; never silently rejected |

## 15. Testing & Validation Strategy

- **Unit:** every formula (BM-01..BM-17) against ≥3 hand-computed fixtures each (typical/boundary/degenerate) — REQ-BIO-035.
- **Integration:** full fan-in → BiomechanicsReport; degradation cases produce correct provisional flags.
- **Contract:** BiomechanicsReport schema consumed by M11/M15/M12/M14/M16.
- **AI/accuracy validation (release-gating):** ≥200 mocap-validated strokes across 3 skill tiers; assert the Section 10 tolerance bands (REQ-BIO-036); regressions block release (ENG-007).
- **Regression:** snapshot reports for a 50-stroke reference set on every change; drift >1 tolerance-band-width blocks merge (REQ-BIO-037).

## 16. Security & Privacy

- Consumes consented derived artefacts + anthropometrics (M04); no raw video.
- Reports are personal data: encrypted at rest, consent-governed access, retention/deletion per Book 3 Ch. 4–5; minors per Book 0 §11.1.
- No keypoints/PII in logs; only correlation_id, metric IDs, and quality summaries.

## 17. Deployment & Monitoring

- CPU worker pool, autoscaled on queue depth (no GPU — GPU is spent upstream).
- Alerts: compute latency vs 3s budget, provisional-rate, out-of-range-flag rate, review-queue backlog.
- Dashboards: metric distributions vs benchmarks, accuracy-vs-golden per metric class over time.

## 18. Claude Code Implementation Guide

Depends on M04, M05, M06, M09 (M07/M08 optional but enable more metrics). Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | Report schema + `biomechanics_reports` migration + review-queue index | Migrations apply/rollback; indexes present |
| 2 | Coordinate normalisation + calibration ingestion (handedness mirroring) | Positional compute in CIP frame; LHB mirrored |
| 3 | Phase alignment from M09 (+ method propagation) | Phase-relative metrics align to boundaries |
| 4 | Implement BM-01..BM-17 with fixtures + Savitzky-Golay filtering | All formula unit tests pass |
| 5 | Confidence/provenance + precondition + degradation rules | Provisional/flags correct per Section 14 |
| 6 | Range validation + review-queue routing | Out-of-range flagged + sampled, not rejected |
| 7 | Publish `biomechanics.metrics` + persist; expose compute/get APIs | Report emitted; M11 consumes without re-deriving |
| 8 | Wire golden-dataset accuracy gate + snapshot regression into CI/CD | Tolerance-band regression blocks release |

## 19. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M10-01 | Given full inputs, M10 emits a BiomechanicsReport with BM-01..BM-17 in the CIP frame. |
| AC-M10-02 | Velocity metrics apply Savitzky-Golay smoothing; hand speed is not jitter-inflated. |
| AC-M10-03 | Low-confidence input yields `provisional` with `LOW_CONFIDENCE_INPUT`; bat loss marks BM-09..BM-13 provisional. |
| AC-M10-04 | Out-of-range values are flagged and sampled to review, never silently rejected. |
| AC-M10-05 | LHB strokes are mirrored so downstream logic is handedness-agnostic. |
| AC-M10-06 | On the mocap golden set, metrics meet the Section 10 tolerance bands; a regressing change is blocked (ENG-007). |
| AC-M10-07 | M11 consumes the report as its sole biomechanical input and does not re-derive kinematics. |
| AC-M10-08 | Compute completes ≤3s per stroke; identical input yields identical output. |

## 20. Appendix — Glossary

| Term | Meaning |
|---|---|
| BiomechanicsReport | The per-stroke output object (BM-01..BM-17 + quality) |
| BM-xx | A canonical CIP-STD biomechanical metric |
| X-Factor | Shoulder–hip separation (BM-04), a power indicator |
| Provisional | Reduced-confidence output flag |
| Tolerance band | Allowed error vs mocap ground truth (release-gating) |
| Savitzky-Golay | Smoothing filter applied before differentiation |
| Handedness-invariant | Metrics identical for RHB/LHB after mirroring |
