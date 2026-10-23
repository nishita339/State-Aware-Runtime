"""
Python Client SDK for State-Aware Durable Runtime.

Allows developers to connect remote agents, LangChain/CrewAI swarms, or custom
LLMs to the distributed SADR cluster with automatic contract enforcement,
real-time telemetry streaming, and anti-fabrication verification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional
import httpx

logger = logging.getLogger(__name__)

__all__ = ["SADRClient", "RemoteSession"]


class RemoteSession:
    """Client-side handle to a remote session on the SADR cluster."""

    def __init__(self, client: SADRClient, session_id: str, objective: str) -> None:
        self.client = client
        self.session_id = session_id
        self.objective = objective

    async def get_bounded_context(self, max_tokens: int = 8192) -> dict[str, Any]:
        """Fetch reconstructed O(1) decision-relevant context."""
        return await self.client.get_context(self.session_id, max_tokens)

    async def propose_and_evaluate(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        rationale: str = "",
        action_type: str = "tool_call",
    ) -> dict[str, Any]:
        """Evaluate action against Pre-Action Gate contracts before executing."""
        return await self.client.evaluate_action(
            self.session_id, tool_name, parameters, rationale, action_type
        )

    async def commit_result(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        output: str,
        state_diff: Optional[dict[str, Any]] = None,
        success: bool = True,
        tokens_used: int = 0,
    ) -> dict[str, Any]:
        """Commit executed tool output to canonical state with memory governance."""
        return await self.client.commit_action(
            self.session_id,
            tool_name,
            parameters,
            output,
            state_diff or {},
            success,
            tokens_used,
        )

    async def claim_completion(
        self,
        artifacts: list[str],
        evidence: Optional[dict[str, Any]] = None,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Submit completion claim to Anti-Fabrication Firewall."""
        return await self.client.claim_completion(
            self.session_id, artifacts, evidence or {}, confidence
        )

    async def get_lineage(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch immutable causal audit trail."""
        return await self.client.get_lineage(self.session_id, limit)


class SADRClient:
    """
    High-performance async client for interacting with the SADR cluster.
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def close(self) -> None:
        """Close underlying HTTP client connections."""
        await self._http_client.aclose()

    async def __aenter__(self) -> SADRClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def health(self) -> dict[str, Any]:
        """Check cluster health status."""
        resp = await self._http_client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def create_session(
        self,
        objective: str,
        tenant_id: str = "default_tenant",
        max_drift_score: float = 0.27,
        initial_state: Optional[dict[str, Any]] = None,
    ) -> RemoteSession:
        """Create a new governed session on the cluster."""
        payload = {
            "objective": objective,
            "tenant_id": tenant_id,
            "max_drift_score": max_drift_score,
            "initial_state": initial_state or {},
        }
        resp = await self._http_client.post("/v1/sessions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return RemoteSession(self, data["session_id"], data["objective"])

    async def list_sessions(self) -> list[str]:
        """List all active or loaded session IDs on the cluster."""
        resp = await self._http_client.get("/v1/sessions")
        resp.raise_for_status()
        return resp.json()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Get telemetry and governance status for a specific session."""
        resp = await self._http_client.get(f"/v1/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_context(self, session_id: str, max_tokens: int = 8192) -> dict[str, Any]:
        """Retrieve bounded O(1) context."""
        resp = await self._http_client.get(
            f"/v1/sessions/{session_id}/context", params={"max_tokens": max_tokens}
        )
        resp.raise_for_status()
        return resp.json()

    async def evaluate_action(
        self,
        session_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        rationale: str = "",
        action_type: str = "tool_call",
    ) -> dict[str, Any]:
        """Pre-action contract evaluation."""
        payload = {
            "action_type": action_type,
            "tool_name": tool_name,
            "parameters": parameters,
            "rationale": rationale,
        }
        resp = await self._http_client.post(
            f"/v1/sessions/{session_id}/actions/evaluate", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def commit_action(
        self,
        session_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        output: str,
        state_diff: dict[str, Any],
        success: bool = True,
        tokens_used: int = 0,
    ) -> dict[str, Any]:
        """Post-action state diff commit."""
        payload = {
            "proposal": {
                "action_type": "tool_call",
                "tool_name": tool_name,
                "parameters": parameters,
            },
            "output": output,
            "state_diff": state_diff,
            "success": success,
            "tokens_used": tokens_used,
        }
        resp = await self._http_client.post(
            f"/v1/sessions/{session_id}/actions/commit", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def claim_completion(
        self,
        session_id: str,
        artifacts: list[str],
        evidence: dict[str, Any],
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Submit claim to Anti-Fabrication Firewall."""
        payload = {
            "subtask_id": "final",
            "artifacts": artifacts,
            "evidence": evidence,
            "confidence": confidence,
        }
        resp = await self._http_client.post(
            f"/v1/sessions/{session_id}/claim-completion", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def get_lineage(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve lineage audit trail."""
        resp = await self._http_client.get(
            f"/v1/sessions/{session_id}/lineage", params={"limit": limit}
        )
        resp.raise_for_status()
        return resp.json()
