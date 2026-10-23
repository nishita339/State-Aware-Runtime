"""
Distributed State & Session Manager.

Coordinates concurrent sessions, memory caches, contract verification,
and real-time notification dispatching.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from state_aware_runtime.config import (
    ActionProposal,
    ActionResult,
    ActionVerdict,
    CompletionVerdict,
    ContractPolicy,
    FirewallPolicy,
    MemoryPolicy,
    MemoryTier,
    MemoryVerdict,
    RecoveryPolicy,
    RuntimeConfig,
    SessionId,
    SubtaskContract,
)
from state_aware_runtime.contracts import BehavioralContract, ContractClause, ContractEngine
from state_aware_runtime.firewall import AntiFabricationFirewall, CompletionClaim, EnvironmentCheck
from state_aware_runtime.lineage import LineageEvent, LineageLogger
from state_aware_runtime.memory_governor import MemoryEntry, MemoryGovernor
from state_aware_runtime.recovery import RecoveryEngine
from state_aware_runtime.server.config import ServerConfig
from state_aware_runtime.server.ws_manager import WebSocketManager
from state_aware_runtime.state_store import StateStore, StateTree

logger = logging.getLogger(__name__)

__all__ = ["SessionContext", "DistributedStateManager"]


class SessionContext:
    """In-memory active execution context for a single agent session."""

    def __init__(
        self,
        session_id: str,
        tenant_id: str,
        objective: str,
        config: RuntimeConfig,
        ws_manager: WebSocketManager,
    ) -> None:
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.objective = objective
        self.config = config
        self.ws_manager = ws_manager
        self.created_at = datetime.now(timezone.utc)
        self.last_accessed = datetime.now(timezone.utc)
        self.lock = asyncio.Lock()

        # Core Engines
        self.state_tree = StateTree()
        self.contract_engine = ContractEngine(config.contract_policy)
        self.memory_governor = MemoryGovernor(config.memory_policy)
        self.recovery_engine = RecoveryEngine(config.recovery_policy, config.state_dir / "checkpoints")
        self.firewall = AntiFabricationFirewall(config.firewall_policy, config.workspace_dir)
        self.lineage = LineageLogger(config.log_dir, session_id)

        # Metrics
        self.total_actions: int = 0
        self.total_tokens: int = 0
        self.status: str = "active"
        self.completion_verified: bool = False
        self.peak_drift: float = 0.0

    async def emit_event(self, event_type: str, actor: str, payload: dict[str, Any], severity: str = "info") -> None:
        """Write to lineage log and broadcast in real-time over WebSocket."""
        event = LineageEvent(
            session_id=self.session_id,
            event_type=event_type,
            actor=actor,
            node_id=str(self.state_tree.active_node_id),
            payload=payload,
            severity=severity,
        )
        self.lineage.emit(event)
        await self.ws_manager.broadcast_to_session(
            self.session_id,
            {
                "event_type": event_type,
                "session_id": self.session_id,
                "timestamp": event.timestamp.isoformat(),
                "actor": actor,
                "severity": severity,
                "payload": payload,
            },
        )


class DistributedStateManager:
    """
    Manages active session instances, handles session lifecycle,
    and supports scaling to millions of users via lazy loading and eviction.
    """

    def __init__(self, server_config: ServerConfig, ws_manager: WebSocketManager) -> None:
        self.config = server_config
        self.ws_manager = ws_manager
        self.state_store = StateStore(server_config.storage_dir)
        self._active_sessions: dict[str, SessionContext] = {}
        self._lock = asyncio.Lock()

    @property
    def active_session_count(self) -> int:
        return len(self._active_sessions)

    async def create_session(
        self,
        objective: str,
        tenant_id: str = "default_tenant",
        max_drift_score: float = 0.27,
        episodic_decay_rate: float = 0.15,
        enable_auto_checkpoint: bool = True,
        initial_state: Optional[dict[str, Any]] = None,
    ) -> SessionContext:
        """Create and initialize a new persistent session."""
        session_id = str(SessionId())
        runtime_config = RuntimeConfig(
            session_id=SessionId(value=session_id),
            workspace_dir=self.config.workspace_dir / session_id,
            state_dir=self.config.storage_dir,
            log_dir=self.config.log_dir,
            contract_policy=ContractPolicy(max_drift_score=max_drift_score),
            memory_policy=MemoryPolicy(episodic_decay_rate=episodic_decay_rate),
            recovery_policy=RecoveryPolicy(enable_auto_checkpoint=enable_auto_checkpoint),
            firewall_policy=FirewallPolicy(require_environment_verification=True, min_verification_checks=1),
        )
        runtime_config.ensure_dirs()

        ctx = SessionContext(
            session_id=session_id,
            tenant_id=tenant_id,
            objective=objective,
            config=runtime_config,
            ws_manager=self.ws_manager,
        )

        if initial_state:
            ctx.state_tree.root.state_data = dict(initial_state)

        # Register default environment check for honest completion
        ctx.firewall.register_check(
            EnvironmentCheck(
                check_type="state_match",
                description="Default state progression check",
                check_fn=lambda ws, st: len(st) > 0,
            )
        )

        # Register default safety contract
        safety_contract = BehavioralContract(name="default_safety_policy")
        safety_contract.add_clause(
            ContractClause(
                clause_type="forbidden",
                description="Prevent destructive filesystem operations (rm -rf / drop table / format)",
                check_fn=lambda act: not any(
                    bad in json.dumps(act.get("parameters", {})).lower()
                    for bad in ["rm -rf", "drop table", "drop database", "format c:"]
                ),
                severity="hard",
            )
        )
        ctx.contract_engine.register_contract(safety_contract)

        # Persist initial tree to disk
        self.state_store.save(ctx.state_tree, session_id)

        async with self._lock:
            self._active_sessions[session_id] = ctx

        await ctx.emit_event(
            event_type="session_started",
            actor="system",
            payload={"objective": objective, "tenant_id": tenant_id},
        )

        logger.info("Created session %s for tenant %s", session_id, tenant_id)
        return ctx

    async def get_session(self, session_id: str) -> Optional[SessionContext]:
        """Retrieve an active session or lazily restore from durable storage."""
        async with self._lock:
            if session_id in self._active_sessions:
                ctx = self._active_sessions[session_id]
                ctx.last_accessed = datetime.now(timezone.utc)
                return ctx

        # Attempt to restore from durable storage
        try:
            tree = self.state_store.load(session_id)
            runtime_config = RuntimeConfig(
                session_id=SessionId(value=session_id),
                workspace_dir=self.config.workspace_dir / session_id,
                state_dir=self.config.storage_dir,
                log_dir=self.config.log_dir,
            )
            ctx = SessionContext(
                session_id=session_id,
                tenant_id=self.config.default_tenant_id,
                objective=tree.root.subtask.objective if tree.root else "Restored task",
                config=runtime_config,
                ws_manager=self.ws_manager,
            )
            ctx.state_tree = tree

            async with self._lock:
                self._active_sessions[session_id] = ctx

            logger.info("Restored session %s from persistent store", session_id)
            return ctx
        except FileNotFoundError:
            return None

    async def list_sessions(self) -> list[str]:
        """List all active and durable session IDs."""
        durable = self.state_store.list_sessions()
        async with self._lock:
            active = list(self._active_sessions.keys())
        return sorted(list(set(durable + active)))

    async def evaluate_action(
        self, session_id: str, proposal: ActionProposal
    ) -> tuple[ActionVerdict, list[str], float]:
        """Evaluate action proposal against behavioral contracts."""
        ctx = await self.get_session(session_id)
        if not ctx:
            raise KeyError(f"Session {session_id} not found")

        async with ctx.lock:
            current_state = ctx.state_tree.get_active_node().state_data
            verdict, reasons = ctx.contract_engine.evaluate_proposal(proposal, current_state)
            drift_status = ctx.contract_engine.get_drift_status()
            current_drift = drift_status.get("current_drift", 0.0)

            if current_drift > ctx.peak_drift:
                ctx.peak_drift = current_drift

            await ctx.emit_event(
                event_type="action_evaluated",
                actor="governor",
                payload={
                    "action_id": proposal.action_id,
                    "tool": proposal.tool_name,
                    "verdict": verdict.name,
                    "reasons": reasons,
                    "current_drift": current_drift,
                },
                severity="info" if verdict == ActionVerdict.APPROVE else "warning",
            )

            return verdict, reasons, current_drift

    async def commit_action_result(
        self,
        session_id: str,
        proposal: ActionProposal,
        result: ActionResult,
    ) -> dict[str, Any]:
        """Commit an approved action execution result to canonical state."""
        ctx = await self.get_session(session_id)
        if not ctx:
            raise KeyError(f"Session {session_id} not found")

        async with ctx.lock:
            active_node = ctx.state_tree.get_active_node()
            active_node.add_action(proposal.to_dict(), result.to_dict())

            ctx.total_actions += 1
            ctx.total_tokens += result.tokens_used

            # Update state with state_diff
            if result.state_diff:
                active_node.state_data.update(result.state_diff)

            # Govern memory writes
            if result.success and result.output:
                entry = MemoryEntry(
                    tier=MemoryTier.EPISODIC,
                    content=f"Tool '{proposal.tool_name}': {result.output[:300]}",
                    source_action_id=proposal.action_id,
                    source_node_id=str(active_node.node_id),
                )
                v, _ = ctx.memory_governor.write(entry)

            # Persist state update
            self.state_store.save(ctx.state_tree, session_id)

            await ctx.emit_event(
                event_type="action_executed" if result.success else "action_failed",
                actor="executor",
                payload={
                    "action_id": proposal.action_id,
                    "success": result.success,
                    "total_actions": ctx.total_actions,
                    "tokens_used": result.tokens_used,
                },
            )

            return {
                "active_node_id": str(active_node.node_id),
                "total_actions": ctx.total_actions,
                "canonical_state": active_node.state_data,
            }

    async def verify_completion_claim(
        self,
        session_id: str,
        claim: CompletionClaim,
    ) -> tuple[CompletionVerdict, float, int, int, bool]:
        """Evaluate completion claim against anti-fabrication firewall."""
        ctx = await self.get_session(session_id)
        if not ctx:
            raise KeyError(f"Session {session_id} not found")

        async with ctx.lock:
            current_state = ctx.state_tree.get_active_node().state_data
            verification = ctx.firewall.verify_claim(claim, current_state)
            allowed = ctx.firewall.is_completion_allowed(verification)

            if allowed:
                ctx.completion_verified = True
                ctx.status = "completed"
                # Mark tree node verified
                ctx.state_tree.get_active_node().mark_verified()
                self.state_store.save(ctx.state_tree, session_id)

            await ctx.emit_event(
                event_type="completion_verified" if allowed else "completion_rejected",
                actor="firewall",
                payload={
                    "verdict": verification.verdict.name,
                    "confidence": verification.confidence,
                    "passed": verification.passed_count,
                    "failed": verification.failed_count,
                    "allowed": allowed,
                },
                severity="info" if allowed else "error",
            )

            return (
                verification.verdict,
                verification.confidence,
                verification.passed_count,
                verification.failed_count,
                allowed,
            )
