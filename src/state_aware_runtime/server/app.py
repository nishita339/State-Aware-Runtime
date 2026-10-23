"""
Production FastAPI Application for State-Aware Durable Runtime.

Exposes RESTful endpoints, bidirectional WebSockets, and real-time telemetry
designed to support horizontal scaling across Kubernetes clusters for millions of users.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pathlib import Path

from state_aware_runtime import __version__
from state_aware_runtime.config import (
    ActionProposal,
    ActionResult,
    ActionVerdict,
    generate_id,
)
from state_aware_runtime.firewall import CompletionClaim
from state_aware_runtime.server.config import ServerConfig
from state_aware_runtime.server.schemas import (
    ActionProposalRequest,
    ActionVerdictResponse,
    ClaimCompletionRequest,
    CreateSessionRequest,
    ExecuteActionRequest,
    LineageEventResponse,
    SessionResponse,
    VerificationResponse,
)
from state_aware_runtime.server.state_manager import DistributedStateManager
from state_aware_runtime.server.ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

# Server configuration & state instances
server_config = ServerConfig()
server_config.ensure_directories()
ws_manager = WebSocketManager()
state_manager = DistributedStateManager(server_config, ws_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    logger.info("SADR Cloud Runtime starting up...")
    yield
    logger.info("SADR Cloud Runtime shutting down...")


app = FastAPI(
    title="State-Aware Durable Runtime API",
    description="Production-grade real-time distributed runtime for reliable long-horizon AI agents.",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware for Web dashboards & IDE plugins
app.add_middleware(
    CORSMiddleware,
    allow_origins=server_config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Dashboard & Telemetry Endpoints
# ============================================================================


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard() -> HTMLResponse:
    """Serve the real-time systems governance web dashboard."""
    html_file = Path(__file__).parent / "static" / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>State-Aware Durable Runtime Dashboard</h1>")


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, Any]:
    """Health check endpoint for Kubernetes liveness/readiness probes."""
    return {
        "status": "healthy",
        "version": __version__,
        "active_sessions": state_manager.active_session_count,
        "active_ws_connections": ws_manager.total_connections,
        "total_broadcasts": ws_manager.total_broadcasts,
    }


@app.get("/metrics", response_class=PlainTextResponse, tags=["System"])
async def prometheus_metrics() -> str:
    """Exposes real-time Prometheus telemetry metrics."""
    return (
        f"# HELP sadr_active_sessions Currently active in-memory agent sessions\n"
        f"# TYPE sadr_active_sessions gauge\n"
        f"sadr_active_sessions {state_manager.active_session_count}\n"
        f"# HELP sadr_ws_connections Active WebSocket streaming connections\n"
        f"# TYPE sadr_ws_connections gauge\n"
        f"sadr_ws_connections {ws_manager.total_connections}\n"
        f"# HELP sadr_total_broadcasts Total real-time events broadcasted\n"
        f"# TYPE sadr_total_broadcasts counter\n"
        f"sadr_total_broadcasts {ws_manager.total_broadcasts}\n"
    )


# ============================================================================
# Session Management Endpoints
# ============================================================================


@app.post("/v1/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED, tags=["Sessions"])
async def create_session(request: CreateSessionRequest) -> SessionResponse:
    """Create a new stateful session with governed contracts and durable state."""
    ctx = await state_manager.create_session(
        objective=request.objective,
        tenant_id=request.tenant_id,
        max_drift_score=request.max_drift_score,
        episodic_decay_rate=request.episodic_decay_rate,
        enable_auto_checkpoint=request.enable_auto_checkpoint,
        initial_state=request.initial_state,
    )
    return SessionResponse(
        session_id=ctx.session_id,
        tenant_id=ctx.tenant_id,
        objective=ctx.objective,
        status=ctx.status,
        created_at=ctx.created_at.isoformat(),
        total_actions=ctx.total_actions,
        total_tokens=ctx.total_tokens,
        peak_drift=ctx.peak_drift,
        current_drift=0.0,
        active_depth=ctx.state_tree.active_depth,
        subtasks_completed=0,
        completion_verified=ctx.completion_verified,
    )


@app.get("/v1/sessions", response_model=list[str], tags=["Sessions"])
async def list_sessions() -> list[str]:
    """List all available session IDs."""
    return await state_manager.list_sessions()


@app.get("/v1/sessions/{session_id}", response_model=SessionResponse, tags=["Sessions"])
async def get_session(session_id: str) -> SessionResponse:
    """Get status and metrics for a specific session."""
    ctx = await state_manager.get_session(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    drift_status = ctx.contract_engine.get_drift_status()
    return SessionResponse(
        session_id=ctx.session_id,
        tenant_id=ctx.tenant_id,
        objective=ctx.objective,
        status=ctx.status,
        created_at=ctx.created_at.isoformat(),
        total_actions=ctx.total_actions,
        total_tokens=ctx.total_tokens,
        peak_drift=ctx.peak_drift,
        current_drift=drift_status.get("current_drift", 0.0),
        active_depth=ctx.state_tree.active_depth,
        subtasks_completed=len(ctx.state_tree.get_active_path()) - 1,
        completion_verified=ctx.completion_verified,
    )


@app.get("/v1/sessions/{session_id}/context", tags=["Context"])
async def get_bounded_context(session_id: str, max_tokens: int = 8192) -> dict[str, Any]:
    """
    Retrieve decision-relevant O(1) context reconstructed from canonical state.
    Eliminates quadratic context growth for LLM proposers.
    """
    ctx = await state_manager.get_session(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return ctx.state_tree.get_context_view(max_tokens=max_tokens)


# ============================================================================
# Action Evaluation & Governance Endpoints
# ============================================================================


@app.post("/v1/sessions/{session_id}/actions/evaluate", response_model=ActionVerdictResponse, tags=["Governance"])
async def evaluate_action(session_id: str, request: ActionProposalRequest) -> ActionVerdictResponse:
    """
    Pre-Action Gate: Evaluates action proposal against behavioral contracts.
    Returns APPROVE, REWRITE, BLOCK, or ROLLBACK before action is dispatched.
    """
    proposal = ActionProposal(
        action_id=generate_id("act"),
        action_type=request.action_type,
        tool_name=request.tool_name,
        parameters=request.parameters,
        rationale=request.rationale,
    )
    try:
        verdict, reasons, current_drift = await state_manager.evaluate_action(session_id, proposal)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return ActionVerdictResponse(
        verdict=verdict.name,
        action_id=proposal.action_id,
        reasons=reasons,
        current_drift=current_drift,
        allowed=(verdict == ActionVerdict.APPROVE),
    )


@app.post("/v1/sessions/{session_id}/actions/commit", tags=["Governance"])
async def commit_action(session_id: str, request: ExecuteActionRequest) -> dict[str, Any]:
    """
    Post-Action Audit & Commit: Commits verified tool results to canonical state.
    Updates the state tree, executes memory governance write validation, and records lineage.
    """
    proposal = ActionProposal(
        action_id=generate_id("act"),
        action_type=request.proposal.action_type,
        tool_name=request.proposal.tool_name,
        parameters=request.proposal.parameters,
        rationale=request.proposal.rationale,
    )
    result = ActionResult(
        action_id=proposal.action_id,
        success=request.success,
        output=request.output,
        state_diff=request.state_diff,
        tokens_used=request.tokens_used,
    )

    try:
        commit_info = await state_manager.commit_action_result(session_id, proposal, result)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return commit_info


# ============================================================================
# Anti-Fabrication Firewall Endpoint
# ============================================================================


@app.post("/v1/sessions/{session_id}/claim-completion", response_model=VerificationResponse, tags=["Firewall"])
async def claim_completion(session_id: str, request: ClaimCompletionRequest) -> VerificationResponse:
    """
    Anti-Fabrication Firewall: Evaluates an agent's completion claim against observable
    environment checks. Blocks false "done" claims structurally.
    """
    claim = CompletionClaim(
        subtask_id=request.subtask_id,
        claimed_artifacts=request.artifacts,
        claimed_evidence=request.evidence,
        agent_confidence=request.confidence,
    )

    try:
        verdict, confidence, passed, failed, allowed = await state_manager.verify_completion_claim(
            session_id, claim
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return VerificationResponse(
        claim_id=claim.claim_id,
        verdict=verdict.name,
        confidence=confidence,
        passed_count=passed,
        failed_count=failed,
        allowed=allowed,
    )


# ============================================================================
# Lineage & Audit Endpoints
# ============================================================================


@app.get("/v1/sessions/{session_id}/lineage", response_model=list[LineageEventResponse], tags=["Lineage"])
async def get_lineage(session_id: str, limit: int = 50) -> list[LineageEventResponse]:
    """Retrieve immutable append-only lineage audit trail for forensic analysis."""
    ctx = await state_manager.get_session(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    events = ctx.lineage.query()[-limit:]
    return [
        LineageEventResponse(
            event_id=e.event_id,
            session_id=e.session_id,
            timestamp=e.timestamp.isoformat(),
            event_type=e.event_type,
            node_id=e.node_id,
            actor=e.actor,
            severity=e.severity,
            payload=e.payload,
        )
        for e in events
    ]


# ============================================================================
# Real-Time WebSocket Streaming Endpoint
# ============================================================================


@app.websocket("/v1/sessions/{session_id}/stream")
async def session_websocket_stream(websocket: WebSocket, session_id: str):
    """
    Real-Time WebSocket Stream: Connect to receive live step-level updates,
    action approvals/rejections, drift metrics, and completion events.
    """
    ctx = await state_manager.get_session(session_id)
    if not ctx:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect(session_id, websocket)
    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "event_type": "connected",
            "session_id": session_id,
            "status": ctx.status,
            "total_actions": ctx.total_actions,
        })

        # Keep connection alive & handle incoming commands (e.g. human-in-the-loop pause/cancel)
        while True:
            data = await websocket.receive_text()
            logger.debug("Received WS message from client: %s", data)
    except WebSocketDisconnect:
        await ws_manager.disconnect(session_id, websocket)
    except Exception as e:
        logger.warning("WS exception: %s", e)
        await ws_manager.disconnect(session_id, websocket)
