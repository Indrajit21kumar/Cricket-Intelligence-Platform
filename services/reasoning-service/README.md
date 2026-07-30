# reasoning-service

M13 — the Reasoning Engine, where measurements become meaning. It takes the
facts about a stroke — biomechanics (M10), physics (M11), shot context (M09) —
executes the coaching rules from the Knowledge Graph (M12) against them, and
produces the platform's core output: **explained findings**, each stating
*what* happened, *why*, its match consequence, and the drill to fix it.

M13 invents no knowledge (that lives in M12) and measures nothing (M10/M11). It
is the inference layer: match facts to rules, resolve conflicts by precedence,
combine confidences, and assemble evidence-linked findings. Every finding traces
to specific metrics and specific rule versions, so the report can always answer
"how do you know?" (ENG-005).

Run locally:

```bash
uv run uvicorn reasoning_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/internal/version
```
