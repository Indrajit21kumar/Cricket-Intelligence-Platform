# physics-service

M11 — the Physics Engine. The platform's core IP: it converts the
BiomechanicsReport from M10 into the physics of the shot — **MEASURED**
kinematics (bat/hand speed, angular velocity, separation, centre of mass,
timing) and **ESTIMATED** dynamics (momentum, torque, energy transfer, ground
reaction force, ball-exit velocity, sweet-spot efficiency). Every quantity
carries a provenance label; every estimate carries a confidence.

M11 is a **pure function** of its inputs (the M10 report + M04 anthropometrics).
It never touches raw video or pose, so it runs and is tested entirely on fixture
reports (the purity boundary, REQ-BIO-029 / AC-M11-02).

Run locally:

```bash
uv run uvicorn physics_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
