# CIP Web Console

The SaaS shell — a React + TypeScript + Tailwind front end over the M02
identity-service APIs. Lets a user register, log in, join/leave an academy,
and see their identity + roles + memberships.

This is the first user-facing surface of CIP. Later modules (billing UI,
video upload, coaching reports) mount into this same console.

## Run it

The identity-service (M02 backend) must be running on `:8000`:

```bash
# terminal 1 — backend
cd ../../   # repo root
python -m uv run uvicorn identity_service.main:app --env-file .env --port 8000

# terminal 2 — this frontend
cd web/console
npm install
npm run dev
```

Then open http://localhost:5180. Vite proxies `/api/*` to the backend so
there is no CORS setup.
