# CIP Web Console

The user-facing surface of CIP — React + TypeScript + Tailwind, built to the
**Book 6 UI/UX Specification**. This is the "real slice" of the frontend: every
screen is backed by a working service (no mock data). The hero Coaching Report
and AI Coach land once M14/M16 exist.

## What's here (Book 6)

- **Design system** (`src/ui/`) — Book 6 tokens (deep-blue brand, slate base,
  and the **provenance palette**) plus the trust primitives `ProvenanceBadge`
  and `ConfidenceIndicator`. Measured / estimated / modelled values are always
  visually distinct, and never by colour alone (WCAG AA / UX-02).
- **Auth & onboarding** (M02) — register → verify → sign in, with the minor
  guardian-consent hint.
- **Analyse a clip** (M05 + M06) — capture-guidance checklist whose thresholds
  come from the server's `/v1/capture-guidance` (so guidance and gate agree);
  pick a real video file → the bytes are PUT to `/v1/videos/{id}/raw` →
  `/complete` runs the quality gate; then the quality result (calibration +
  confidence on admit, or a specific, non-punitive re-film prompt from the
  gate's own reasons on reject, UX-04), followed by the **pose run** for the
  clip polled from pose-service.
- **Progress & Cricket DNA** (M04) — editable player attributes, the DNA trait
  fingerprint (with provenance + confidence per trait), and trend charts vs the
  player's baseline. DNA/trends populate once M16 is live.

## Run it

Infra first (Postgres/Redis/Redpanda), then the services, then the frontend:

```bash
make infra-up
```

One command starts every service the console needs, on the ports the Vite
proxy expects (`--migrate` is only needed the first time):

```bash
uv run python scripts/run_console_stack.py --real --migrate
```

```bash
cd web/console && npm install && npm run dev
```

Then open http://localhost:5180.

### Fake vs real pipeline

`--real` is what makes the analysis genuinely read your footage. It sets
`CIP_USE_REAL_PIPELINE=true` (M05: local-disk storage + OpenCV preprocessing)
and `CIP_USE_REAL_POSE_MODEL=true` (M06: real clip decode + YOLOv8-pose), and
needs the optional extras:

```bash
uv pip install opencv-python-headless ultralytics
```

Without `--real` the stack still runs end to end, but the measurements and
keypoints are synthetic — identical for any file you upload. The Analyse
screen says so explicitly when the model reports a `fake-` version.

### What the console covers

Four of the platform's twenty services are wired to this UI: identity (M02),
profile (M04), video (M05) and pose (M06). Bat, ball and shot detection have
no trained models, so biomechanics, physics, reasoning and coaching reports
are not derived from your clip and are not shown here.

## Build

```bash
npm run build   # tsc --strict + vite build
```
