"""Start the services the web console talks to, on the ports it expects.

The console reaches four services through Vite's dev proxy plus one background
worker that turns an admitted clip into a pose run:

    identity-service (M02)  :8000   auth, /v1/me, memberships
    profile-service  (M04)  :8002   attributes, Cricket DNA, progress
    video-service    (M05)  :8003   upload, quality gate, calibration
    pose-service     (M06)  :8004   pose run for a clip
    pose worker      (M06)  --      consumes video.normalized

The other 15 services are not wired to the console and are not started here.

Prerequisites:
  * infra up (``make infra-up`` — Postgres, Redis, Redpanda)
  * migrations applied (``--migrate`` does this for you)
  * ``.env`` present (copy from ``.env.example``)

Usage::

    uv run python scripts/run_console_stack.py             # fake pipeline
    uv run python scripts/run_console_stack.py --real      # real CV + pose
    uv run python scripts/run_console_stack.py --real --migrate

``--real`` needs the optional extras installed::

    uv pip install opencv-python-headless ultralytics

Then run the frontend separately::

    cd web/console && npm install && npm run dev     # http://localhost:5180

Ctrl-C stops every child process.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess  # nosec B404 -- launches this repo's own services, fixed argv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: (label, argv) for each process. Ports match web/console/vite.config.ts.
SERVICES: list[tuple[str, list[str]]] = [
    ("identity :8000", ["uvicorn", "identity_service.main:app", "--port", "8000"]),
    ("profile  :8002", ["uvicorn", "profile_service.main:app", "--port", "8002"]),
    ("video    :8003", ["uvicorn", "video_service.main:app", "--port", "8003"]),
    ("pose     :8004", ["uvicorn", "pose_service.main:app", "--port", "8004"]),
    ("pose worker   ", [sys.executable, "-m", "pose_service.worker"]),
]

#: Kept in step with pose_service.service (imported lazily so this script can
#: still print --help without the service packages installed).
TOPIC_VIDEO_NORMALIZED = "video.normalized"
POSE_CONSUMER_GROUP = "pose-engine"

MIGRATIONS = [
    ("base", REPO_ROOT / "migrations" / "base"),
    ("identity", REPO_ROOT / "services" / "identity-service" / "migrations"),
    ("profile", REPO_ROOT / "services" / "profile-service" / "migrations"),
    ("video", REPO_ROOT / "services" / "video-service" / "migrations"),
    ("pose", REPO_ROOT / "services" / "pose-service" / "migrations"),
]


def apply_migrations(database_url: str) -> None:
    from cip_data.migrations import upgrade_head

    for label, path in MIGRATIONS:
        print(f"  migrating {label} …", flush=True)
        upgrade_head(database_url, migrations_dir=path)
    print("  migrations applied\n", flush=True)


def load_dotenv(env: dict[str, str]) -> None:
    """Merge ``.env`` into the child environment.

    ``ServiceSettings`` reads ``.env`` itself, but ``cip_core.secrets`` with
    ``CIP_SECRET_PROVIDER=env`` reads the real process environment — so a
    child started without these set fails at the first JWT signing. Existing
    environment variables win, so an explicit export still overrides the file.
    """
    dotenv = REPO_ROOT / ".env"
    if not dotenv.is_file():
        print("  note: no .env found — services may fail to find secrets\n", flush=True)
        return
    for raw in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env.setdefault(key.strip(), value.strip().strip("\"'"))


def skip_event_backlog(bootstrap: str) -> None:
    """Park the pose worker's consumer group at the end of the topic.

    A long-lived dev broker accumulates ``video.normalized`` events from past
    test runs whose clips were never written to this machine's storage root.
    Under the REAL pipeline the loader rightly fails on every one of them, so
    a fresh worker wedges on the backlog and never reaches the clip you just
    uploaded. Seeking to the end drops that history for this group only; it
    changes no code path and no other consumer.
    """
    import asyncio

    from aiokafka import AIOKafkaConsumer

    async def _seek() -> None:
        consumer = AIOKafkaConsumer(
            TOPIC_VIDEO_NORMALIZED,
            bootstrap_servers=bootstrap,
            group_id=POSE_CONSUMER_GROUP,
            enable_auto_commit=False,
        )
        await consumer.start()
        try:
            await consumer.seek_to_end()
            await consumer.commit()
        finally:
            await consumer.stop()

    try:
        asyncio.run(_seek())
        print(f"  skipped stale {TOPIC_VIDEO_NORMALIZED} backlog for '{POSE_CONSUMER_GROUP}'\n")
    except Exception as exc:  # advisory step — never fatal to starting the stack
        print(f"  note: could not skip the event backlog ({exc})\n")


def build_env(*, real: bool) -> dict[str, str]:
    env = dict(os.environ)
    load_dotenv(env)
    if real:
        # Both flags default to False in settings; the console's "real" mode
        # needs storage+processor (M05) and loader+model (M06) together.
        env["CIP_USE_REAL_PIPELINE"] = "true"
        env["CIP_USE_REAL_POSE_MODEL"] = "true"
        # Must match the port video-service is served on below, since the
        # minted upload_url points back at this service's own API.
        env.setdefault("CIP_PUBLIC_BASE_URL", "http://127.0.0.1:8003")
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use the real OpenCV pipeline + real pose model instead of the fakes",
    )
    parser.add_argument(
        "--migrate", action="store_true", help="Apply base + service migrations before starting"
    )
    parser.add_argument(
        "--keep-backlog",
        action="store_true",
        help=(
            "Process queued video.normalized events instead of skipping to the "
            "end. Stale events from past runs will fail under --real."
        ),
    )
    args = parser.parse_args()

    database_url = os.environ.get(
        "CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip"
    )
    if args.migrate:
        print("Applying migrations…", flush=True)
        apply_migrations(database_url)

    env = build_env(real=args.real)
    if not args.keep_backlog:
        skip_event_backlog(env.get("CIP_KAFKA_BOOTSTRAP", "localhost:9092"))

    mode = "REAL (OpenCV + YOLOv8-pose)" if args.real else "FAKE (synthetic measurements/pose)"
    print(f"Starting the console stack — pipeline mode: {mode}\n", flush=True)

    procs: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        for label, argv in SERVICES:
            proc = subprocess.Popen(argv, cwd=REPO_ROOT, env=env)  # nosec B603 -- fixed argv
            procs.append((label, proc))
            print(f"  started {label}  (pid {proc.pid})", flush=True)

        print("\nConsole stack up. Now run the frontend:", flush=True)
        print("  cd web/console && npm run dev      ->  http://localhost:5180", flush=True)
        print("\nCtrl-C to stop everything.\n", flush=True)

        # Surface an early crash (bad port, missing extra) instead of leaving a
        # half-up stack that fails confusingly in the browser.
        while True:
            for label, proc in procs:
                if proc.poll() is not None:
                    print(f"\n{label} exited with code {proc.returncode}.", flush=True)
                    return proc.returncode or 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping…", flush=True)
        return 0
    finally:
        for _label, proc in procs:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        for _label, proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
