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
- **Analyse a clip** (M05) — capture-guidance checklist whose thresholds come
  from the server's `/v1/capture-guidance` (so guidance and gate agree), the
  upload → `/complete` flow, and the quality result: calibration + confidence
  on admit, or a specific, non-punitive re-film prompt from the gate's own
  reasons on reject (UX-04).
- **Progress & Cricket DNA** (M04) — editable player attributes, the DNA trait
  fingerprint (with provenance + confidence per trait), and trend charts vs the
  player's baseline. DNA/trends populate once analysis (M06+/M16) is live.

## Run it

Each service defaults to `:8000`, so run them on distinct ports and let Vite
proxy per-service prefixes (`/api/identity`, `/api/profile`, `/api/video`):

```bash
# from the repo root — one terminal each (or & them)
python -m uv run uvicorn identity_service.main:app --port 8000   # M02
python -m uv run uvicorn profile_service.main:app  --port 8002   # M04
python -m uv run uvicorn video_service.main:app    --port 8003   # M05

# the frontend
cd web/console && npm install && npm run dev
```

Then open http://localhost:5180. The console needs Postgres/Redis/Redpanda up
(the usual `docker/docker-compose.yml`) for the services to run.

## Build

```bash
npm run build   # tsc --strict + vite build
```
