# cip-annotation

The training-data flywheel: consented frames are routed for human labelling,
frozen into a versioned corpus, and used to retrain the vision models — which
then record the `dataset_version` they learned from.

Shared because the flywheel is platform-wide, not per-module. M07 (bat) and M08
(ball) both name `annotation_queue` in their specs, and the consent gate that
guards it must exist in **one audited implementation** — the same reasoning that
put `check_profile_access` in `cip-core`. Copying it per service would mean
copying the rule that protects children's data.

## What lives here

- `queue.py` — consent-gated admission (`enqueue_frames`), withdrawal
  (`purge_person`), counting, and the `modality` split between bat and ball
  frames of the same clip.
- `dataset.py` — freezing the queue into a named, checksummed corpus so a
  model is always traceable to exactly the frames it trained on.

## What does NOT live here

**Frame selection.** Which frames are worth a human's time is module-specific:
M07 wants low-confidence bat frames, M08 wants deliveries. Each service decides
that itself and hands the result here. Keeping selection out is deliberate —
"which frames are useful" must never drift into "which frames are allowed".

## Schema ownership

The `annotation_queue` and `annotation_datasets` tables are created by
**bat-service's** Alembic project, which introduced them in M07, and extended
there (`0003_annotation_modality`) when M08 began sharing them. One service owns
the DDL; every service uses the tables through this library.
