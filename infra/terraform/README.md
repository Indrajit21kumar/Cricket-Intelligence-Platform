# infra/terraform

Provider-agnostic Terraform scaffold. No cloud is bound in M01 — nothing here
provisions any real resources. When a cloud is chosen (recommended: GCP, decided
at the M01→M02 handoff), we fill in:

- `providers.tf` — pin the cloud provider version
- `environments/{dev,staging,prod}/` — per-env `main.tf` composing modules
- `modules/` — reusable modules (network, db, cluster, event-bus, secret-manager, storage)

See `docs/specs/CIP_Book2_Reference_Architecture_v1.0.md` Ch. 8 and
`docs/specs/CIP_Book3_Engineering_Standards_v1.0.md` Ch. 7 for what the IaC must
express (IaC-only production changes; separate dev/staging/prod; canary rollout;
scale-to-zero GPU pool; etc.).
