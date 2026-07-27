# knowledge-service

M12 — the Cricket Knowledge Graph. Where the founder's cricket expertise becomes
software: a governed, versioned graph of typed entities (Shots, Faults, Causes,
Risks, Drills, Sources) and coaching rules in the canonical
**Fault → Cause → Risk → Drill** format.

M12 *holds and serves* knowledge; it does not reason over a specific stroke —
that is M13, which executes these rules against the facts from M10/M11. Keeping
knowledge (M12) separate from reasoning (M13) makes rules **data**: reviewable,
versioned, and improvable by cricket experts without touching code.

The knowledge is **platform-global** (coaching IP, not personal data) — so the
tables carry no `tenant_id` and no RLS; authoring is instead RBAC-gated and fully
audited.

Run locally:

```bash
uv run uvicorn knowledge_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
