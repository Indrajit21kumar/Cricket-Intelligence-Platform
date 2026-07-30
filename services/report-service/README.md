# report-service

M14 — the platform's voice. It turns M13's grounded findings — plus the metrics
(M10/M11), Legend benchmarks (M15), and player history (M04) — into two things
a player uses: a clear, explained **coaching report** (scores, findings,
metric panels, Legend comparison, annotated video), and an interactive **AI
Coach** ("Cricket GPT") the player can ask questions of.

M14 is the one module that calls an LLM, and it is deliberately constrained:
the model narrates and answers **only** from grounded evidence — M13 findings,
M12 rules with citations, the player's own metrics and history. It never
invents coaching advice; when evidence is insufficient it defers rather than
fabricates.

Run locally:

```bash
uv run uvicorn report_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/internal/version
```
