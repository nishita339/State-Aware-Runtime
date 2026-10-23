"""
Tests for State-Aware Durable Runtime Production API & WebSocket Server.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from state_aware_runtime.server.app import app


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client


class TestServerAPI:
    """Test suite for server endpoints."""

    def test_health_check(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "active_sessions" in data

    def test_prometheus_metrics(self, client: TestClient):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "sadr_active_sessions" in response.text
        assert "sadr_ws_connections" in response.text

    def test_session_lifecycle_and_actions(self, client: TestClient):
        # 1. Create a new session
        create_resp = client.post(
            "/v1/sessions",
            json={
                "objective": "Build high-throughput microservice",
                "tenant_id": "tenant_enterprise_01",
                "initial_state": {"git_repo": "initialized"},
            },
        )
        assert create_resp.status_code == 201
        session_data = create_resp.json()
        session_id = session_data["session_id"]
        assert session_id.startswith("sess_")
        assert session_data["status"] == "active"

        # 2. Get session details
        get_resp = client.get(f"/v1/sessions/{session_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["session_id"] == session_id

        # 3. Retrieve O(1) context view
        context_resp = client.get(f"/v1/sessions/{session_id}/context")
        assert context_resp.status_code == 200
        ctx_data = context_resp.json()
        assert "canonical_state" in ctx_data

        # 4. Evaluate an action (Pre-Action Gate)
        eval_resp = client.post(
            f"/v1/sessions/{session_id}/actions/evaluate",
            json={
                "action_type": "tool_call",
                "tool_name": "git_commit",
                "parameters": {"message": "initial commit"},
                "rationale": "Save starting state",
            },
        )
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        assert eval_data["verdict"] == "APPROVE"
        assert eval_data["allowed"] is True

        # 5. Commit executed action results (Post-Action Audit)
        commit_resp = client.post(
            f"/v1/sessions/{session_id}/actions/commit",
            json={
                "proposal": {
                    "action_type": "tool_call",
                    "tool_name": "git_commit",
                    "parameters": {"message": "initial commit"},
                    "rationale": "Save starting state",
                },
                "output": "Committed hash 8fa10b",
                "state_diff": {"commit_hash": "8fa10b"},
                "success": True,
                "tokens_used": 150,
            },
        )
        assert commit_resp.status_code == 200
        commit_data = commit_resp.json()
        assert commit_data["total_actions"] == 1
        assert commit_data["canonical_state"]["commit_hash"] == "8fa10b"

        # 6. Verify completion claim via Anti-Fabrication Firewall
        claim_resp = client.post(
            f"/v1/sessions/{session_id}/claim-completion",
            json={
                "subtask_id": "final",
                "artifacts": ["main.py"],
                "evidence": {"commit_hash": "8fa10b"},
                "confidence": 0.99,
            },
        )
        assert claim_resp.status_code == 200
        claim_data = claim_resp.json()
        assert claim_data["allowed"] is True
        assert claim_data["verdict"] == "GENUINE"

        # 7. Query Lineage Audit Log
        lineage_resp = client.get(f"/v1/sessions/{session_id}/lineage")
        assert lineage_resp.status_code == 200
        events = lineage_resp.json()
        assert len(events) >= 3
        event_types = [e["event_type"] for e in events]
        assert "session_started" in event_types
        assert "action_evaluated" in event_types

    def test_websocket_stream(self, client: TestClient):
        # Create session first
        create_resp = client.post(
            "/v1/sessions",
            json={"objective": "Test real-time WebSocket streaming"},
        )
        session_id = create_resp.json()["session_id"]

        # Connect WebSocket
        with client.websocket_connect(f"/v1/sessions/{session_id}/stream") as websocket:
            initial_msg = websocket.receive_json()
            assert initial_msg["event_type"] == "connected"
            assert initial_msg["session_id"] == session_id
