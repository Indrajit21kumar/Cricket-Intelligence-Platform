"""Authoring workflow + RBAC (M12 Step 3, §6, AC-M12-07).

Proves the draft -> review -> approve lifecycle over the real app, and the
governance negatives that make the knowledge trustworthy: only authoring roles
may author, only reviewers may approve, a reviewer may not approve their own
rule, only a draft may be edited, and a malformed rule is rejected.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio

from cip_core import roles
from knowledge_service.domain.rule_schema import WORKED_EXAMPLE
from knowledge_service.main import create_app

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


@pytest_asyncio.fixture
async def client(_migrated_database: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


def _token(person_id: uuid.UUID, *claim_roles: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(person_id),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _headers(person_id: uuid.UUID, *claim_roles: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(person_id, *claim_roles)}"}


def _rule() -> dict[str, Any]:
    body = copy.deepcopy(WORKED_EXAMPLE)
    # Unique rule_id per test run so reruns don't collide on the version key.
    body["rule_id"] = f"KG-TEST-{uuid.uuid4().hex[:6].upper()}"
    return body


AUTHOR = uuid.uuid4()
REVIEWER = uuid.uuid4()


class TestAuthoring:
    async def test_full_workflow_draft_review_approve(self, client: httpx.AsyncClient) -> None:
        # Author drafts.
        r = await client.post(
            "/v1/kg/rules", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json=_rule()
        )
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["status"] == "draft"
        row_id = row["id"]

        # Author submits for review.
        r = await client.patch(
            f"/v1/kg/rules/{row_id}",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"submit": True},
        )
        assert r.status_code == 200 and r.json()["status"] == "in_review", r.text

        # A distinct reviewer approves.
        r = await client.post(
            f"/v1/kg/rules/{row_id}/review",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"decision": "approve"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        assert r.json()["reviewer"] == str(REVIEWER)

    async def test_edit_then_get_history(self, client: httpx.AsyncClient) -> None:
        body = _rule()
        r = await client.post(
            "/v1/kg/rules", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json=body
        )
        row_id = r.json()["id"]
        r = await client.patch(
            f"/v1/kg/rules/{row_id}",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"confidence": 0.77},
        )
        assert r.status_code == 200 and r.json()["confidence"] == 0.77, r.text
        r = await client.get(
            f"/v1/kg/rules/{body['rule_id']}", headers=_headers(AUTHOR, roles.RULE_AUTHOR)
        )
        assert r.status_code == 200
        assert r.json()["versions"][0]["confidence"] == 0.77


class TestGovernanceNegatives:
    async def test_a_non_authoring_role_cannot_create(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/v1/kg/rules", headers=_headers(AUTHOR, roles.PLAYER), json=_rule())
        assert r.status_code == 403

    async def test_a_non_reviewer_cannot_approve(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/v1/kg/rules", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json=_rule()
        )
        row_id = r.json()["id"]
        await client.patch(
            f"/v1/kg/rules/{row_id}",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"submit": True},
        )
        # An author (no reviewer role) may not approve.
        r = await client.post(
            f"/v1/kg/rules/{row_id}/review",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"decision": "approve"},
        )
        assert r.status_code == 403

    async def test_a_reviewer_cannot_approve_their_own_rule(
        self, client: httpx.AsyncClient
    ) -> None:
        """Separation of duties: author == reviewer is refused."""
        same = uuid.uuid4()
        r = await client.post(
            "/v1/kg/rules", headers=_headers(same, roles.RULE_REVIEWER), json=_rule()
        )
        row_id = r.json()["id"]
        await client.patch(
            f"/v1/kg/rules/{row_id}",
            headers=_headers(same, roles.RULE_REVIEWER),
            json={"submit": True},
        )
        r = await client.post(
            f"/v1/kg/rules/{row_id}/review",
            headers=_headers(same, roles.RULE_REVIEWER),
            json={"decision": "approve"},
        )
        assert r.status_code == 403, r.text

    async def test_only_a_draft_can_be_edited(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/v1/kg/rules", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json=_rule()
        )
        row_id = r.json()["id"]
        await client.patch(
            f"/v1/kg/rules/{row_id}",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"submit": True},
        )
        # Now in_review — editing content must be refused.
        r = await client.patch(
            f"/v1/kg/rules/{row_id}",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"confidence": 0.5},
        )
        assert r.status_code == 409, r.text

    async def test_a_malformed_rule_is_rejected(self, client: httpx.AsyncClient) -> None:
        bad = _rule()
        bad["confidence"] = 5.0  # out of [0,1]
        r = await client.post("/v1/kg/rules", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json=bad)
        assert r.status_code == 422, r.text

    async def test_unauthenticated_is_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/v1/kg/rules", json=_rule())
        assert r.status_code == 401


async def _drive_to_approved(client: httpx.AsyncClient, body: dict[str, Any]) -> str:
    """create (author) -> submit -> approve (reviewer); return the row id."""
    r = await client.post("/v1/kg/rules", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json=body)
    row_id = r.json()["id"]
    await client.patch(
        f"/v1/kg/rules/{row_id}", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json={"submit": True}
    )
    await client.post(
        f"/v1/kg/rules/{row_id}/review",
        headers=_headers(REVIEWER, roles.RULE_REVIEWER),
        json={"decision": "approve"},
    )
    return str(row_id)


class TestRelease:
    async def test_approved_rule_can_be_released(self, client: httpx.AsyncClient) -> None:
        """AC-M12-02 (positive): an approved rule reaches the served graph."""
        row_id = await _drive_to_approved(client, _rule())
        r = await client.post(
            "/v1/kg/release",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"row_id": row_id},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "released"

    async def test_a_draft_cannot_be_released(self, client: httpx.AsyncClient) -> None:
        """AC-M12-02: only an approved rule may be released, never a draft."""
        r = await client.post(
            "/v1/kg/rules", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json=_rule()
        )
        row_id = r.json()["id"]
        r = await client.post(
            "/v1/kg/release",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"row_id": row_id},
        )
        assert r.status_code == 409, r.text

    async def test_release_requires_reviewer_role(self, client: httpx.AsyncClient) -> None:
        row_id = await _drive_to_approved(client, _rule())
        r = await client.post(
            "/v1/kg/release", headers=_headers(AUTHOR, roles.RULE_AUTHOR), json={"row_id": row_id}
        )
        assert r.status_code == 403

    async def test_releasing_a_new_version_supersedes_the_old(
        self, client: httpx.AsyncClient
    ) -> None:
        """AC-M12-03: the old version remains (superseded) for reproduction."""
        rule_id = f"KG-SUP-{uuid.uuid4().hex[:6].upper()}"
        v1 = {**_rule(), "rule_id": rule_id, "version": 1}
        v1_id = await _drive_to_approved(client, v1)
        await client.post(
            "/v1/kg/release",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"row_id": v1_id},
        )
        v2 = {**_rule(), "rule_id": rule_id, "version": 2}
        v2_id = await _drive_to_approved(client, v2)
        await client.post(
            "/v1/kg/release",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"row_id": v2_id},
        )

        r = await client.get(f"/v1/kg/rules/{rule_id}", headers=_headers(AUTHOR, roles.RULE_AUTHOR))
        by_version = {v["version"]: v["status"] for v in r.json()["versions"]}
        assert by_version == {1: "superseded", 2: "released"}


def _marker_rule(marker: str) -> dict[str, Any]:
    """A rule keyed by a unique context marker so tests never collide."""
    body = _rule()
    body["conditions"] = [{"kind": "context", "field": "test_marker", "op": "eq", "value": marker}]
    return body


class TestMatchServing:
    async def test_a_released_rule_matches_facts(self, client: httpx.AsyncClient) -> None:
        marker = uuid.uuid4().hex
        row_id = await _drive_to_approved(client, _marker_rule(marker))
        await client.post(
            "/v1/kg/release",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"row_id": row_id},
        )
        r = await client.post(
            "/internal/kg/match",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"context": {"test_marker": marker}},
        )
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 1
        assert r.json()["matched"][0]["fault"]  # served with its content

    async def test_an_unreleased_rule_never_matches(self, client: httpx.AsyncClient) -> None:
        """AC-M12-02: an approved-but-unreleased rule cannot reach reasoning."""
        marker = uuid.uuid4().hex
        await _drive_to_approved(client, _marker_rule(marker))  # approved, NOT released
        r = await client.post(
            "/internal/kg/match",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"context": {"test_marker": marker}},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 0

    async def test_non_matching_facts_return_nothing(self, client: httpx.AsyncClient) -> None:
        marker = uuid.uuid4().hex
        row_id = await _drive_to_approved(client, _marker_rule(marker))
        await client.post(
            "/v1/kg/release",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"row_id": row_id},
        )
        r = await client.post(
            "/internal/kg/match",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"context": {"test_marker": "a-different-marker"}},
        )
        assert r.status_code == 200
        assert marker not in [m["rule_id"] for m in r.json()["matched"]]


class TestRagServing:
    async def test_released_rule_grounds_with_citation(self, client: httpx.AsyncClient) -> None:
        """AC-M12-05: RAG results carry rule_id/version citations."""
        body = _marker_rule(uuid.uuid4().hex)
        rule_id = body["rule_id"]
        row_id = await _drive_to_approved(client, body)
        await client.post(
            "/v1/kg/release",
            headers=_headers(REVIEWER, roles.RULE_REVIEWER),
            json={"row_id": row_id},
        )
        r = await client.post(
            "/internal/kg/query",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"rule_ids": [rule_id]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 1
        assert r.json()["results"][0]["citation"] == {"rule_id": rule_id, "version": 1}

    async def test_unreleased_rule_is_not_grounded(self, client: httpx.AsyncClient) -> None:
        body = _marker_rule(uuid.uuid4().hex)
        await _drive_to_approved(client, body)  # approved, NOT released
        r = await client.post(
            "/internal/kg/query",
            headers=_headers(AUTHOR, roles.RULE_AUTHOR),
            json={"rule_ids": [body["rule_id"]]},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 0
