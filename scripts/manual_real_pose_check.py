"""Manual end-to-end check: two real videos -> two real pose runs.

Proves the real path is genuinely reading the footage, by running two
different clips all the way through M05 -> M06 and printing the results side
by side. If the two columns are identical, the pipeline is still faked.

Prerequisites (see the README section this script's output points at):
  1. The ``real`` extras installed for video-service + pose-service.
  2. ``make infra-up`` + base/video/pose migrations applied.
  3. ``.env`` with CIP_USE_REAL_PIPELINE=true, CIP_USE_REAL_POSE_MODEL=true,
     CIP_PUBLIC_BASE_URL=http://127.0.0.1:8001
  4. Both services running:
       uv run uvicorn video_service.main:app --port 8001
       uv run uvicorn pose_service.main:app  --port 8002

Usage:
    uv run python scripts/manual_real_pose_check.py clip_a.mp4 clip_b.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt
from sqlalchemy import text

from cip_data.engine import admin_session, build_engine, build_session_factory

VIDEO_URL = "http://127.0.0.1:8001"
POSE_URL = "http://127.0.0.1:8002"
DATABASE_URL = os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")

# Fields worth eyeballing: every one of these is fixed on the fake path.
VIDEO_FIELDS = ("frame_count", "fps", "camera_angle", "spatial_confidence", "admitted")
POSE_FIELDS = ("model_version", "frame_count", "mean_confidence", "subject_status", "quality")


def _token() -> str:
    secret = os.environ.get("CIP_JWT_SIGNING_KEY")
    if not secret:
        raise SystemExit("CIP_JWT_SIGNING_KEY is not set — check your .env")
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "roles": ["player"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        secret,
        algorithm="HS256",
    )


async def _create_tenant() -> uuid.UUID:
    engine = build_engine(DATABASE_URL)
    tid = uuid.uuid4()
    try:
        async with admin_session(build_session_factory(engine)) as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) "
                    "VALUES (:id, :name, 'academy', 'IN')"
                ),
                {"id": tid, "name": f"real-pose-check-{uuid.uuid4().hex[:8]}"},
            )
    finally:
        await engine.dispose()
    return tid


async def _run_one(
    client: httpx.AsyncClient, headers: dict[str, str], clip: Path
) -> dict[str, Any]:
    """POST /videos -> PUT raw bytes -> POST /complete -> pose compute -> GET pose."""
    created = (
        (
            await client.post(
                f"{VIDEO_URL}/v1/videos",
                headers=headers,
                json={
                    "person_id": str(uuid.uuid4()),
                    "source_type": "mobile",
                    "content_type": "video/mp4",
                    "size_bytes": clip.stat().st_size,
                },
            )
        )
        .raise_for_status()
        .json()
    )

    upload = await client.put(created["upload_url"], headers=headers, content=clip.read_bytes())
    upload.raise_for_status()

    complete = await client.post(
        f"{VIDEO_URL}/v1/videos/{created['ingestion_id']}/complete", headers=headers
    )
    if complete.status_code == 422:
        # The quality gate rejected it — still a real, content-dependent result.
        return {"clip": clip.name, "rejected_by_quality_gate": complete.json()["error"]["details"]}
    video = complete.raise_for_status().json()

    pose = (
        (
            await client.post(
                f"{POSE_URL}/internal/pose/compute",
                headers=headers,
                json={
                    "correlation_id": created["correlation_id"],
                    "normalized_ref": video["normalized_ref"],
                    "camera_angle": video["camera_angle"],
                    "spatial_confidence": video["spatial_confidence"],
                },
            )
        )
        .raise_for_status()
        .json()
    )

    row: dict[str, Any] = {"clip": clip.name, "bytes_uploaded": upload.json()["bytes_received"]}
    row.update({f"video.{k}": video.get(k) for k in VIDEO_FIELDS})
    row.update({f"pose.{k}": pose.get(k) for k in POSE_FIELDS})
    return row


def _print_table(rows: list[dict[str, Any]]) -> None:
    keys: list[str] = []
    for row in rows:
        keys.extend(k for k in row if k not in keys)
    width = max(len(k) for k in keys)
    print()
    for key in keys:
        cells = "  |  ".join(f"{row.get(key, '-')!s:<28}" for row in rows)
        print(f"{key:<{width}}  {cells}")
    print()
    print("Genuinely real if: the two columns differ, video.frame_count/fps match")
    print("each clip's true properties, and pose.model_version is not 'fake-pose-v1'.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clips", nargs=2, type=Path, help="Two different real video files")
    args = parser.parse_args()
    for clip in args.clips:
        if not clip.is_file():
            raise SystemExit(f"No such file: {clip}")

    tenant_id = await _create_tenant()
    headers = {"Authorization": f"Bearer {_token()}", "X-Tenant-ID": str(tenant_id)}
    async with httpx.AsyncClient(timeout=300.0) as client:
        rows = [await _run_one(client, headers, clip) for clip in args.clips]
    _print_table(rows)


if __name__ == "__main__":
    asyncio.run(main())
