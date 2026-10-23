"""
Tests for SADR Python Client SDK and Web Dashboard.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from state_aware_runtime.client import SADRClient
from state_aware_runtime.server.app import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_dashboard_endpoint(client: TestClient):
    """Test that the real-time web dashboard HTML is served properly."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "State-Aware Durable Runtime" in response.text
    assert "WebSocket Live" in response.text


@pytest.mark.asyncio
async def test_client_sdk_full_flow():
    """Test SADRClient interacting with the runtime server asynchronously."""
    # Using httpx ASGITransport for in-memory FastAPI testing
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        client_sdk = SADRClient(base_url="http://testserver")
        client_sdk._http_client = http_client

        # 1. Health
        health = await client_sdk.health()
        assert health["status"] == "healthy"

        # 2. Create Session
        session = await client_sdk.create_session(
            objective="Deploy resilient autonomous swarm",
            tenant_id="enterprise_cluster_01",
            initial_state={"cluster_nodes": 12},
        )
        assert session.session_id.startswith("sess_")

        # 3. Get O(1) context
        ctx = await session.get_bounded_context()
        assert "canonical_state" in ctx
        assert ctx["canonical_state"]["cluster_nodes"] == 12

        # 4. Propose & Evaluate
        verdict = await session.propose_and_evaluate(
            tool_name="scale_nodes",
            parameters={"replicas": 24},
            rationale="Handle traffic spike",
        )
        assert verdict["verdict"] == "APPROVE"
        assert verdict["allowed"] is True

        # 5. Commit Action
        commit = await session.commit_result(
            tool_name="scale_nodes",
            parameters={"replicas": 24},
            output="Scaled to 24 replicas",
            state_diff={"cluster_nodes": 24},
            success=True,
            tokens_used=120,
        )
        assert commit["canonical_state"]["cluster_nodes"] == 24

        # 6. Claim Completion via Firewall
        claim = await session.claim_completion(
            artifacts=["k8s-cluster.log"],
            evidence={"cluster_nodes": 24},
        )
        assert claim["allowed"] is True
        assert claim["verdict"] == "GENUINE"

        # 7. Check Lineage
        events = await session.get_lineage()
        assert len(events) >= 3

        # 8. Test list_sessions and get_session
        sessions_list = await client_sdk.list_sessions()
        assert session.session_id in sessions_list

        session_meta = await client_sdk.get_session(session.session_id)
        assert session_meta["session_id"] == session.session_id
        assert session_meta["tenant_id"] == "enterprise_cluster_01"

        # 9. Test default forbidden contract intercepts destructive action
        bad_verdict = await session.propose_and_evaluate(
            tool_name="bash",
            parameters={"command": "rm -rf /"},
            rationale="Clean up files",
        )
        assert bad_verdict["verdict"] == "BLOCK"
        assert bad_verdict["allowed"] is False
