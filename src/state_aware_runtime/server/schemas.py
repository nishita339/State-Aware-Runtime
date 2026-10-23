"""
API Schemas for State-Aware Durable Runtime Server.

Defines Pydantic request and response models for REST API and WebSocket events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    objective: str = Field(..., description="High-level goal for the long-horizon agent")
    tenant_id: str = Field(default="default_tenant", description="Tenant ID for multi-tenant isolation")
    max_drift_score: float = Field(default=0.27, description="ABC drift boundary threshold")
    episodic_decay_rate: float = Field(default=0.15, description="Memory decay rate for episodic memories")
    enable_auto_checkpoint: bool = Field(default=True, description="Enable automatic subgoal checkpointing")
    initial_state: dict[str, Any] = Field(default_factory=dict, description="Initial workspace canonical state")


class SessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    objective: str
    status: str  # "active", "completed", "failed", "rolled_back"
    created_at: str
    total_actions: int = 0
    total_tokens: int = 0
    peak_drift: float = 0.0
    current_drift: float = 0.0
    active_depth: int = 0
    subtasks_completed: int = 0
    completion_verified: bool = False


class ActionProposalRequest(BaseModel):
    action_type: str = Field(..., description="Type of action (tool_call, shell_exec, etc.)")
    tool_name: str = Field(..., description="Name of the tool to invoke")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action arguments")
    rationale: str = Field(default="", description="LLM rationale for this action")


class ActionVerdictResponse(BaseModel):
    verdict: str  # "APPROVE", "REWRITE", "BLOCK", "ROLLBACK"
    action_id: str
    reasons: list[str] = Field(default_factory=list)
    current_drift: float = 0.0
    allowed: bool = True


class ExecuteActionRequest(BaseModel):
    proposal: ActionProposalRequest
    output: str = Field(..., description="Raw output resulting from tool execution")
    state_diff: dict[str, Any] = Field(default_factory=dict, description="Observable state changes")
    success: bool = Field(default=True, description="Whether execution was successful")
    tokens_used: int = Field(default=0, description="Tokens consumed")


class ClaimCompletionRequest(BaseModel):
    subtask_id: str = Field(default="final", description="Subtask or task ID")
    artifacts: list[str] = Field(default_factory=list, description="Claimed created files/artifacts")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Concrete evidence data")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Self-reported confidence")


class VerificationResponse(BaseModel):
    claim_id: str
    verdict: str  # "GENUINE", "FABRICATED", "INCOMPLETE", "UNVERIFIABLE"
    confidence: float
    passed_count: int
    failed_count: int
    allowed: bool
    evidence_hashes: dict[str, str] = Field(default_factory=dict)


class CheckpointResponse(BaseModel):
    checkpoint_id: str
    session_id: str
    node_id: str
    created_at: str
    size_bytes: int


class LineageEventResponse(BaseModel):
    event_id: str
    session_id: str
    timestamp: str
    event_type: str
    node_id: str
    actor: str
    severity: str
    payload: dict[str, Any] = Field(default_factory=dict)


class WebSocketEvent(BaseModel):
    event_type: str  # "action_proposed", "action_evaluated", "state_committed", "drift_alert", etc.
    session_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)
