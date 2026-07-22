# Module M05 — Video Intelligence

**CIP Blueprint · Volume 6 (Module Specifications)**

---

## Document Control

| Field | Value |
|---|---|
| Document ID | CIP-M05-VID |
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

- Module M01 — Platform Foundation (event client, tenancy, object storage access, audit)
- Module M02 — Identity & Authentication (who is uploading; consent)
- Module M03 — Subscription & Billing (analysis quota / entitlement check)
- Module M04 — Player Profile (player attributes for calibration context)
- Book 2 — Reference Architecture (Intelligence Plane; pipeline; event contracts; <60s SLA)
- Book 3 — Engineering Standards (data, security, testing, DoD)
- Book 4 — CIP-STD Ch. 2 (coordinate frame, calibration conventions)

**Feeds Into (Downstream)**

- M06 Pose Engine, M07 Bat Detection, M08 Ball Tracking, M09 Shot Recognition
- Publishes `video.normalized` (+ calibration, quality flags) to the event bus

---

## Contents

1. Executive Summary
2. Business Context
3. Scope & Responsibilities
4. Personas & Users
5. Processing Pipeline & Quality Gate
6. Functional Requirements
7. Non-Functional Requirements
8. Architecture
9. Database Design
10. API Specification
11. Capture Guidance (Client-Side Contract)
12. Security & Privacy
13. Testing Strategy
14. Deployment & Monitoring
15. Future Enhancements
16. Claude Code Implementation Guide
17. Acceptance Criteria
18. Appendix — Glossary

---

## 1. Executive Summary

Module M05, Video Intelligence, is the entry point to the entire analysis pipeline. It receives an uploaded batting clip, prepares it for machine perception (stabilisation, frame extraction, noise reduction, lighting normalisation), determines the camera angle and derives the pixel-to-metric calibration the downstream engines need, and — critically — runs a **quality gate** that rejects or flags unusable clips *before* any expensive GPU work begins. It also defines the **capture-guidance contract** the mobile app uses to help players film good clips in the first place, which is the single highest-leverage factor on downstream accuracy.

M05 turns a messy real-world smartphone video into a normalised clip plus a metadata envelope (calibration, camera angle, quality flags) and publishes it as `video.normalized`. Everything after M05 — pose, bat, ball, biomechanics, physics — depends on the quality and calibration M05 establishes.

## 2. Business Context

Book 1 and the feasibility study both concluded that capture quality, not model sophistication, is the dominant driver of accuracy from monocular phone video. M05 is therefore where the platform protects its own trustworthiness: good capture guidance plus a strict quality gate prevents the pipeline from producing confident-looking nonsense from an unusable clip. It also protects unit economics — GPU is the biggest cost, and M05 ensures GPU is spent only on analysable video.

M05 is also the first stage that consumes a billable analysis unit; it checks entitlement (M03) before admitting a clip to the pipeline.

## 3. Scope & Responsibilities

### 3.1 In scope

| Capability | Description |
|---|---|
| Ingestion | Accept uploads (mobile, DSLR, nets, match) via signed URLs to object storage |
| Preprocessing | Stabilisation, frame extraction, noise reduction, lighting normalisation |
| Camera-angle detection | Classify viewing angle (side-on, front-on, square, other) |
| Calibration | Derive pixel-to-metric scale + `spatial_confidence` (Book 4 Ch. 2) |
| Quality gate | Reject/flag clips unfit for analysis before GPU work |
| Capture-guidance contract | Define the on-device overlay signals the app should enforce |
| Entitlement check | Confirm analysis quota with M03 before admitting to the pipeline |
| Output | Publish `video.normalized` + metadata envelope |

### 3.2 Out of scope

- Pose/bat/ball detection (M06–M08), analysis (M10+), and the mobile UI itself (M05 defines the contract; the app implements it under M18/M-mobile).

## 4. Personas & Users

| Persona | Need from M05 |
|---|---|
| Player | Simple upload; clear guidance so the clip is usable; fast rejection if not |
| Coach | Bulk/session uploads that pass the quality gate |
| Downstream engines (M06–M09) | A normalised clip + reliable calibration + quality flags |
| Platform/SRE | Predictable preprocessing cost and latency |

## 5. Processing Pipeline & Quality Gate

```
Upload → validate container/codec → stabilise → extract frames → denoise →
lighting-normalise → detect camera angle → derive calibration (scale + confidence) →
QUALITY GATE → publish video.normalized  (or 422 with reasons)
```

### 5.1 Quality gate checks (MUST run before GPU)

| Check | Fail/flag condition |
|---|---|
| Resolution / frame rate | Below minimum usable threshold |
| Motion blur / focus | Excessive blur on the batter region |
| Occlusion / framing | Batter not fully in frame for the stroke |
| Lighting | Under/over-exposed beyond correctable range |
| Camera angle | Unsupported angle → proceed with `spatial_confidence: low` + user recommendation |
| Duration | Too short/long to contain a complete stroke |

Gate policy: a hard fail returns 422 with actionable reasons (surfaced to the user); a soft flag proceeds with reduced-confidence metadata so downstream stages degrade gracefully (Book 2 pipeline; Book 4 Ch. 2).

## 6. Functional Requirements

| ID | Requirement (MUST unless noted) |
|---|---|
| FR-M05-01 | Accept uploads to object storage via signed URLs; validate container/codec/size. |
| FR-M05-02 | Check analysis entitlement with M03 before admitting a clip; deny with a clear reason if quota exhausted. |
| FR-M05-03 | Stabilise, extract frames, denoise, and lighting-normalise the clip. |
| FR-M05-04 | Detect and classify the camera angle. |
| FR-M05-05 | Derive pixel-to-metric calibration and `spatial_confidence` per Book 4 Ch. 2 (stump reference when visible, else player height from M04). |
| FR-M05-06 | Run the quality gate; hard-fail unusable clips (422 + reasons) and soft-flag reduced-quality clips. |
| FR-M05-07 | Publish `video.normalized` with the normalised clip reference + calibration + camera angle + quality flags + correlation_id. |
| FR-M05-08 | Record a metered `analysis.consumed` usage event to M03 when a clip is admitted (idempotent). |
| FR-M05-09 | Persist processing metadata and quality results linked by correlation_id. |
| FR-M05-10 | Emit capture-quality feedback the client can show the user (SHOULD, for re-film prompts). |
| FR-M05-11 | Record ingestion and gate decisions to the M01 audit/observability layer. |

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-M05-01 | Preprocessing MUST complete within the 3–8s stage budget (Book 2, Ch. 3). |
| NFR-M05-02 | The quality gate MUST run before any GPU stage to protect cost. |
| NFR-M05-03 | Every output metric of calibration MUST carry `spatial_confidence` and, for depth, `depth_estimated` (Book 4). |
| NFR-M05-04 | Raw and normalised video MUST be stored per tenant/player namespaces with lifecycle tiering (Book 3, Ch. 4). |
| NFR-M05-05 | Processing MUST be idempotent per correlation_id (safe re-delivery). |

## 8. Architecture

M05 is an **Intelligence-Plane** service (CPU + optional GPU) that consumes `video.uploaded`, does numerical/image preprocessing, and produces `video.normalized`. It reads player attributes from M04 (for height-based calibration fallback) and checks/records billing with M03. Preprocessing is CPU-bound; only later stages (M06–M08) require sustained GPU.

```
video.uploaded → M05 [ validate → M03 entitlement → preprocess → angle → calibrate → QUALITY GATE ]
   ├─ pass → store normalised clip → publish video.normalized (+metadata) → M03 usage.recorded
   └─ fail → 422 + reasons → client re-film prompt (no GPU spent)
```

## 9. Database Design

| Table | Key columns | Notes |
|---|---|---|
| ingestions | id, tenant_id, person_id, correlation_id, source_type, raw_ref, status, created_at | One row per uploaded clip |
| processing_results | id, ingestion_id, normalized_ref, frame_count, fps, created_at | Preprocessing output refs |
| calibrations | id, ingestion_id, pixel_to_meter, camera_angle, spatial_confidence, depth_estimated | Calibration envelope (Book 4 Ch. 2) |
| quality_flags | id, ingestion_id, code, severity, message | Gate decisions (fail/flag) |

All tenant-scoped; `correlation_id` threads the clip through the pipeline. Object references point to tenant/player-namespaced storage.

## 10. API Specification

| Method & path | Purpose |
|---|---|
| POST /v1/videos | Create ingestion; return signed upload URL |
| POST /v1/videos/{id}/complete | Mark upload complete; begin processing |
| GET /v1/videos/{id} | Ingestion status + quality flags + calibration |
| GET /v1/videos/{id}/quality | Detailed quality-gate result (for re-film UX) |
| (event) video.normalized | Internal: emitted to downstream engines |

Standards: versioned paths, standard error envelope (422 for gate failures with reasons), idempotency keys, signed storage URLs (Book 3, Ch. 3–5).

## 11. Capture Guidance (Client-Side Contract)

M05 defines the signals the mobile app should enforce at capture time to maximise usable clips (the app implements the UI; M05 owns the contract and thresholds).

- **Angle:** guide the user to a supported viewing angle (e.g. side-on) with an on-screen frame.
- **Distance/framing:** keep the full batter and stroke in frame.
- **Lighting:** warn on under/over-exposure before recording.
- **Stability:** encourage a fixed camera (tripod/prop) to reduce stabilisation loss.
- **Reference object:** encourage stumps in frame to improve calibration confidence.

The same thresholds power both the pre-capture overlay and the post-upload quality gate, so guidance and gate agree.

## 12. Security & Privacy

- Uploads via signed, time-limited URLs; validate type/size server-side.
- Video is personal data: encrypted at rest, tenant/player-namespaced, consent-governed (M02), with retention/deletion per Book 3 Ch. 4–5 and special care for minors (Book 0 §11.1).
- No video frames or PII in logs; only references and quality codes.
- Ingestion and gate decisions audited with correlation_id.

## 13. Testing Strategy

- **Unit:** calibration math (stump- and height-based); angle classification; each quality-gate check (typical/boundary/failure fixtures — Book 3, Ch. 6).
- **Integration:** upload → preprocess → gate → `video.normalized` emitted with correct metadata; quota exhausted → clip denied; re-delivery is idempotent.
- **Contract:** `video.normalized` schema consumed by M06–M09; quality-result schema for the client.
- **Golden/quality:** a labelled set of good/marginal/bad clips MUST be gated correctly (no bad clip passes; no good clip is wrongly rejected beyond an agreed error rate).
- **Cost guard:** verify the gate runs before any GPU stage (NFR-M05-02).

## 14. Deployment & Monitoring

- CPU workers (with optional GPU for any learned preprocessing) autoscaled on queue depth (Book 3, Ch. 7).
- Alerts: preprocessing latency vs budget, gate-fail rate, calibration-confidence distribution, storage growth.
- Dashboards: clips ingested, pass/flag/fail rates, average `spatial_confidence`, re-film prompt rate.

## 15. Future Enhancements

- On-device pre-gate (reject before upload to save bandwidth).
- Learned stabilisation/lifting to improve monocular depth confidence (feeds Book 1 Ch. 8/11 research).
- Multi-clip / multi-angle fusion for higher calibration accuracy.

## 16. Claude Code Implementation Guide

Depends on M01–M04. Each step ends at the Book 3 Definition of Done.

| Step | Task | Done when |
|---|---|---|
| 1 | Schema + migrations (ingestions, processing_results, calibrations, quality_flags) | Migrations apply/rollback; correlation_id threaded |
| 2 | Signed-URL upload + validation + M03 entitlement gate | Upload works; over-quota clip denied with reason |
| 3 | Preprocessing (stabilise, frame extract, denoise, lighting) | Normalised clip produced within stage budget |
| 4 | Camera-angle detection | Supported angles classified; unsupported flagged |
| 5 | Calibration (stump + height fallback) with confidence | Calibration + spatial_confidence emitted per Book 4 Ch. 2 |
| 6 | Quality gate (all checks) + 422 reasons / soft flags | Bad clips fail before GPU; marginal clips flagged |
| 7 | Publish `video.normalized` + record `analysis.consumed` (idempotent) | Downstream event correct; usage metered once |
| 8 | Capture-guidance contract + client quality-result API | Thresholds shared by overlay and gate |

## 17. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AC-M05-01 | An admitted clip is normalised and `video.normalized` is published with calibration, camera angle, and quality flags. |
| AC-M05-02 | The quality gate runs before any GPU stage; a labelled bad clip hard-fails with actionable reasons (422). |
| AC-M05-03 | Calibration carries `spatial_confidence` (and `depth_estimated`) consistent with Book 4 Ch. 2. |
| AC-M05-04 | An over-quota upload is denied by the M03 entitlement check with a clear reason. |
| AC-M05-05 | Exactly one `analysis.consumed` usage event is recorded per admitted clip (idempotent on re-delivery). |
| AC-M05-06 | Preprocessing completes within the 3–8s stage budget on the target hardware. |
| AC-M05-07 | Video is stored per tenant/player namespace, encrypted, consent-governed; no frames/PII in logs. |

## 18. Appendix — Glossary

| Term | Meaning |
|---|---|
| Normalised clip | Stabilised, denoised, lighting-corrected video ready for perception |
| Calibration | Pixel-to-metric scale + confidence (Book 4 Ch. 2) |
| Quality gate | Pre-GPU checks that reject/flag unusable clips |
| spatial_confidence | high/medium/low confidence in positional scale |
| depth_estimated | Flag that Z (depth) is inferred from monocular video |
| Capture guidance | On-device signals to help users film usable clips |
| video.normalized | The event M05 publishes to downstream engines |
