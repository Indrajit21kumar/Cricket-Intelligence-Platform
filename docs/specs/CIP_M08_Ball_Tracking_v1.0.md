# Module M08 — Ball Tracking

**CIP Blueprint · Volume 6 (Module Specifications)**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M08-BALL |
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
- Module M05 — Video Intelligence (`video.normalized` + calibration + fps + quality flags)
- Book 2 — Reference Architecture (Intelligence Plane; pipeline; GPU pools)
- Book 3 — Engineering Standards (data, testing, AI validation gate, DoD)
- Book 4 — CIP-STD Ch. 2–4 (frame; ground-contact timing BM-17; ball-derived physics)

**Feeds Into (Downstream)**

- M09 Shot Recognition (contact context), M10 Biomechanics (release/contact timing for BM-17)
- M11 Physics (ball-exit velocity — ESTIMATED); publishes `ball.events`

---

## Contents

1. Executive Summary
2. Business Context (the hardest vision task)
3. Scope & Responsibilities
4. Personas & Consumers
5. Ball Events & Output Schema
6. Functional Requirements
7. Non-Functional Requirements
8. Architecture & Graceful Degradation
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

Module M08, Ball Tracking, detects the cricket ball across a delivery and derives its key events — release, bounce, contact — and its line, length, and estimated speed. These events are what let the rest of the pipeline reason about *timing*: the Biomechanics Engine (M10) measures ground-contact timing relative to the bowler's release (BM-17), and the Physics Engine (M11) uses contact to frame ball-exit-velocity estimates. Where M06 sees the body and M07 sees the bat, M08 sees the ball.

M08 is, by design, the most cautious module in the vision stack. Tracking a small, fast, often motion-blurred ball from a single smartphone is the hardest perception task in the platform, and it works reliably only under good capture conditions. The spec therefore centres on **honest confidence and graceful degradation**: when the ball cannot be tracked reliably, M08 says so, and the pipeline continues on body/bat evidence with timing reported in absolute terms rather than fabricated release-relative precision.

## 2. Business Context (the hardest vision task)

The feasibility study rated ball tracking the hardest vision component — research systems succeed only under "constrained capture conditions." Two physical facts drive this: the ball is small, and at 30–60 fps a fast delivery is a motion-blurred streak spanning several pixels. M08 is therefore built to add value where conditions allow (good light, fixed camera, adequate frame rate) and to fail safely where they don't — never to invent a trajectory.

Because of this, M08 is sequenced for **Phase 2** (Book 0 roadmap): the Phase-1 batting product delivers biomechanics without depending on ball tracking, and M08 enriches it once capture quality and models are proven. Nothing in Phase 1 breaks if M08 is absent.

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Ball detection | Locate the ball per frame under adequate conditions |
| Event detection | Release, bounce, and contact frames |
| Line & length | Where the ball pitches and its line relative to stumps |
| Speed estimation | Approximate delivery speed (ESTIMATED, with confidence) |
| Confidence & degradation | Per-event confidence; explicit fallback when unreliable |
| Capture-condition gating | Require adequate fps/lighting; flag when below threshold |

### 3.2 Out of scope

- Spin estimation (future), bat detection (M07), biomechanical interpretation (M10), and physics estimation (M11). M08 provides ball events; others interpret them.

## 4. Personas & Consumers

| Consumer | Need from M08 |
|---|---|
| M10 Biomechanics Engine | release_frame + contact_frame for timing (BM-17) |
| M09 Shot Recognition | Contact context to disambiguate shots |
| M11 Physics Engine | Contact + speed for ball-exit-velocity estimates (ESTIMATED) |
| ML/validation | Versioned tracker measurable against the golden dataset |

## 5. Ball Events & Output Schema

M08 emits discrete events plus per-event confidence, not a guaranteed continuous trajectory.

| Output | Meaning |
|---|---|
| release_frame | Frame of bowler release (timing anchor) |
| bounce_frame | Frame of pitch bounce |
| contact_frame | Frame of bat–ball contact |
| line | Ball line relative to stumps |
| length | Pitching length classification |
| speed_estimate | Approximate delivery speed (ESTIMATED) + confidence |
| track_confidence | Overall tracking confidence for the delivery |
| timing_reference | `release_relative` or `absolute` (fallback) |

All positional outputs use the CIP frame + calibration (Book 4 Ch. 2); speed is explicitly ESTIMATED (Book 4 Ch. 4).

## 6. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M08-01 | Consume `video.normalized` and attempt ball detection per frame using fps/calibration from M05. |
| FR-M08-02 | Detect release, bounce, and contact frames with per-event confidence. |
| FR-M08-03 | Classify line and length relative to the stumps where detected. |
| FR-M08-04 | Produce an ESTIMATED delivery speed with a confidence value (never presented as measured). |
| FR-M08-05 | Gate on capture conditions (fps/lighting); when below threshold or tracking confidence is low, set `track_confidence` low and degrade gracefully. |
| FR-M08-06 | When release cannot be reliably detected, emit `timing_reference = absolute` so M10 uses absolute timing (matches biomechanics fallback). |
| FR-M08-07 | Publish `ball.events` (events + confidence + timing_reference) with correlation_id. |
| FR-M08-08 | Serve a versioned tracker; support canary/rollback (ENG-007). |
| FR-M08-09 | Route consented deliveries to the annotation pipeline for dataset growth (SHOULD). |
| FR-M08-10 | Persist the ball-track artefact to object storage linked by correlation_id. |

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-M08-01 | Ball tracking MUST fit within the vision stage budget (parallel to M06/M07). |
| NFR-M08-02 | GPU workers MUST autoscale on queue depth and scale to zero when idle. |
| NFR-M08-03 | Speed and any trajectory-derived value MUST be labelled ESTIMATED with confidence (Book 4 Ch. 4). |
| NFR-M08-04 | Processing MUST be idempotent per correlation_id. |
| NFR-M08-05 | M08 MUST fail safe: low confidence yields explicit flags + fallback, never fabricated events. |
| NFR-M08-06 | Tracker changes MUST pass the golden-dataset validation gate before production (ENG-007). |

## 8. Architecture & Graceful Degradation

M08 is a GPU-served **Intelligence-Plane** service running parallel to M06/M07. Its defining property is degradation behaviour: the downstream pipeline is designed to work with or without reliable ball events.

```
video.normalized → M08 [ capture-condition gate → detect ball → events (release/bounce/contact) →
   line/length → speed(EST) → confidence ] → ball.events
   ├─ good conditions → release_relative timing + speed(EST)
   └─ poor conditions → low track_confidence, timing_reference=absolute, no fabricated events
```

Downstream contract: M10 uses `release_frame` when present (release_relative timing) and falls back to absolute timing otherwise; low ball confidence also triggers the biomechanics phase-segmentation fallback (bat-only), consistent with the Book 1 flagship chapter (REQ-BIO-008).

## 9. Data & Artefact Design

| Store | Holds |
|---|---|
| Object storage | Per-frame ball detections / track artefact, referenced by correlation_id |
| ball_runs (DB) | id, correlation_id, model_version, track_confidence, timing_reference, events(JSONB), quality, created_at |
| annotation_queue | Consented deliveries routed for labelling (dataset growth) |

## 10. API / Event Specification

| Interface | Purpose |
|---|---|
| (event in) video.normalized | Trigger: normalised clip + fps + calibration |
| (event out) ball.events | Events + confidence + timing_reference |
| GET /v1/ball/{correlationId} | Internal status/summary |
| POST /internal/ball/compute | Internal synchronous entry (tests / reprocessing) |

Event schemas versioned in the schema registry (Book 2 Ch. 4).

## 11. AI Design & Algorithms

- **Detection under blur:** the ball may appear as a streak; detection combines appearance with motion cues (frame differencing / trajectory continuity) rather than relying on a crisp circular blob.
- **Event detection:** release/bounce/contact inferred from the trajectory and, for contact, proximity to the bat (M07) and a change in ball direction.
- **Speed estimation:** derived from displacement between frames and calibration; explicitly ESTIMATED with confidence (Book 4 Ch. 4); higher frame rates improve it.
- **Fail-safe:** if the capture-condition gate or track confidence is below threshold, M08 emits low confidence and `timing_reference = absolute`; it never fabricates a release or contact frame.
- **Tracker:** a custom-trained detector + temporal tracker, versioned in the registry.

## 12. Security & Privacy

- Operates on consented, tenant/player-namespaced video (M02/M05); artefacts encrypted at rest.
- Consent-governed training-data capture; minors per Book 0 §11.1.
- No frames/PII in logs; only correlation_id, model_version, and quality summaries.

## 13. Testing & Validation Strategy

- **Unit:** event detection from synthetic trajectories; speed derivation from known displacement; capture-condition gating; fallback to absolute timing (typical/boundary/failure).
- **Integration:** parallel run with M06/M07; `ball.events` schema correct; low-confidence path sets `timing_reference=absolute` and triggers M10 bat-only fallback.
- **Contract:** `ball.events` schema consumed by M09/M10/M11.
- **AI validation (release-gating, ENG-007):** event-detection accuracy and speed error MUST meet targets on the golden dataset under the supported condition profile; regressions block release.
- **Fail-safe tests:** on deliberately poor clips, M08 MUST NOT emit fabricated events (AC-M08-05).

## 14. Deployment & Monitoring

- GPU pool, autoscaled, scale-to-zero; tracker pinned and canaried (ENG-007).
- Alerts: ball-stage latency, track-confidence distribution, fallback (absolute-timing) rate, annotation backlog.
- Dashboards: successful-track rate by capture condition, speed-estimate confidence, dataset growth.

## 15. Future Enhancements

- Spin estimation (explicitly deferred in the v1 PRD).
- Higher-frame-rate capture guidance (M05) to improve speed and event accuracy.
- Multi-camera or sensor fusion for validation of ball-exit-velocity estimates (M11).

## 16. Claude Code Implementation Guide

Phase 2 module. Depends on M01, M05, M07 (for contact association). Requires a labelled ball dataset under supported conditions. Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | GPU worker scaffold + model-registry integration | Pinned tracker loads/serves; scales to zero |
| 2 | Capture-condition gate (fps/lighting thresholds) | Sub-threshold clips flagged low-confidence up front |
| 3 | Ball detection under blur (appearance + motion) | Ball detected on supported-condition validation clips |
| 4 | Event detection (release/bounce/contact) + line/length | Events emitted with per-event confidence |
| 5 | Speed estimation (ESTIMATED + confidence) | Speed labelled estimated; error within target |
| 6 | Fail-safe + timing_reference fallback | Poor clips → absolute timing, no fabricated events |
| 7 | Publish `ball.events` (idempotent) + annotation routing | Event correct; M10 fallback honoured; flywheel active |
| 8 | Wire golden-dataset validation gate into CI/CD | Tracker change blocked if accuracy regresses beyond target |

## 17. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M08-01 | Under supported conditions, M08 emits release/bounce/contact frames with per-event confidence. |
| AC-M08-02 | Line/length are classified relative to the stumps where detected. |
| AC-M08-03 | Speed is emitted as ESTIMATED with a confidence value, never as measured. |
| AC-M08-04 | When release is not reliably detected, `timing_reference=absolute` is set and M10 uses absolute timing. |
| AC-M08-05 | On deliberately poor clips, M08 emits low confidence and NO fabricated events (fail-safe). |
| AC-M08-06 | `ball.events` is published with correct schema and correlation_id; re-delivery is idempotent. |
| AC-M08-07 | A tracker change that regresses event accuracy beyond target is blocked by the validation gate (ENG-007). |

## 18. Appendix — Glossary

| Term | Meaning |
|---|---|
| Release / bounce / contact | The three key ball events M08 detects |
| Line / length | Ball position relative to stumps / pitching distance |
| timing_reference | `release_relative` (normal) or `absolute` (fallback) |
| track_confidence | Overall confidence in the delivery's tracking |
| ESTIMATED | Provenance class for modelled values (speed) — Book 4 |
| Fail-safe | Emit flags/fallback, never fabricated events |
| ball.events | The event M08 publishes to downstream modules |
