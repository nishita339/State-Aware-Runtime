"""
State-Aware Durable Runtime — Unified Orchestrator
====================================================

This is the central integration layer that ties all seven core components
into a unified execution engine:

    1. StateStore       — Hierarchical State Trees (MAGE) for externalized state
    2. MEALoop          — Manage-Execute-Audit with strict role isolation
    3. ContractEngine   — Pre/In/Post action gates for behavioral enforcement
    4. MemoryGovernor   — Write-path validation, anti-poisoning, selective decay
    5. RecoveryEngine   — Semantics-aware checkpointing & branch-isolated rollback
    6. Firewall         — Anti-fabrication verification of completion claims
    7. LineageLogger    — Append-only causal audit trail

The runtime implements the Proposer-Governor-Persistence architecture:
    - PROPOSAL SURFACE:  LLM operates in ephemeral sandbox, proposes actions
    - GOVERNANCE LAYER:  Contracts verify/block/rewrite before state changes
    - PERSISTENCE LAYER: Canonical state survives across sessions

Key Differences from Existing Systems:
    - CaveAgent has state but no contracts → We add formal enforcement
    - ABC has contracts but no memory lifecycle → We add governed memory
    - Springdrift has audit but no anti-fabrication → We add verification firewall
    - Crab has checkpoints but no drift control → We add behavioral monitoring

References:
    All referenced papers are cited in individual component modules.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from state_aware_runtime.config import (
    ActionProposal,
    ActionResult,
    ActionVerdict,
    CompletionVerdict,
    DriftSeverity,
    MemoryTier,
    MemoryVerdict,
    RecoveryStrategy,
    RuntimeConfig,
    SessionId,
    StatePhase,
    SubtaskContract,
    generate_id,
)
from state_aware_runtime.contracts import ContractEngine, BehavioralContract
from state_aware_runtime.firewall import (
    AntiFabricationFirewall,
    CompletionClaim,
)
from state_aware_runtime.lineage import (
    CausalTracer,
    LineageEvent,
    LineageLogger,
)
from state_aware_runtime.mea_loop import (
    AgentInterface,
    MEALoop,
    MEAResult,
    ToolExecutor,
)
from state_aware_runtime.memory_governor import MemoryEntry, MemoryGovernor
from state_aware_runtime.recovery import RecoveryEngine
from state_aware_runtime.state_store import StateStore, StateTree

logger = logging.getLogger(__name__)

__all__ = [
    "StatefulRuntime",
    "RuntimeSession",
    "RuntimeMetrics",
]


# ============================================================================
# Runtime Metrics
# ============================================================================


@dataclass
class RuntimeMetrics:
    """
    Aggregated metrics for a runtime session.

    Tracks performance across all dimensions relevant to long-horizon
    agent reliability:
        - Success/failure rates
        - Drift scores
        - Recovery statistics
        - Token efficiency
        - Memory lifecycle stats
        - Contract compliance
    """

    session_id: str = ""
    total_actions: int = 0
    total_tokens: int = 0
    total_subtasks: int = 0
    successful_subtasks: int = 0
    failed_subtasks: int = 0
    revisions: int = 0
    total_time_ms: float = 0.0

    # Drift control
    peak_drift_score: float = 0.0
    average_drift_score: float = 0.0
    drift_violations: int = 0

    # Contract compliance
    total_contract_checks: int = 0
    hard_violations: int = 0
    soft_violations: int = 0
    actions_blocked: int = 0
    actions_rewritten: int = 0
    compliance_rate: float = 1.0

    # Recovery
    total_failures: int = 0
    successful_recoveries: int = 0
    rollbacks: int = 0
    recovery_rate: float = 0.0

    # Memory
    memory_writes: int = 0
    memory_rejections: int = 0
    memory_quarantines: int = 0
    memory_decay_events: int = 0

    # Anti-fabrication
    completion_claims: int = 0
    genuine_completions: int = 0
    fabricated_completions: int = 0

    # Efficiency
    context_tokens_saved: int = 0
    checkpoint_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_actions": self.total_actions,
            "total_tokens": self.total_tokens,
            "total_subtasks": self.total_subtasks,
            "successful_subtasks": self.successful_subtasks,
            "failed_subtasks": self.failed_subtasks,
            "revisions": self.revisions,
            "total_time_ms": self.total_time_ms,
            "drift": {
                "peak": self.peak_drift_score,
                "average": self.average_drift_score,
                "violations": self.drift_violations,
            },
            "contracts": {
                "total_checks": self.total_contract_checks,
                "hard_violations": self.hard_violations,
                "soft_violations": self.soft_violations,
                "blocked": self.actions_blocked,
                "rewritten": self.actions_rewritten,
                "compliance_rate": self.compliance_rate,
            },
            "recovery": {
                "failures": self.total_failures,
                "successful": self.successful_recoveries,
                "rollbacks": self.rollbacks,
                "rate": self.recovery_rate,
            },
            "memory": {
                "writes": self.memory_writes,
                "rejections": self.memory_rejections,
                "quarantines": self.memory_quarantines,
                "decay_events": self.memory_decay_events,
            },
            "anti_fabrication": {
                "claims": self.completion_claims,
                "genuine": self.genuine_completions,
                "fabricated": self.fabricated_completions,
            },
            "efficiency": {
                "context_tokens_saved": self.context_tokens_saved,
                "checkpoints": self.checkpoint_count,
            },
        }


# ============================================================================
# Runtime Session
# ============================================================================


@dataclass
class RuntimeSession:
    """
    Encapsulates the state of a single runtime session.

    A session is the unit of cross-session continuity — it can be
    saved, restored, and resumed across process restarts.
    """

    session_id: str = field(default_factory=lambda: str(SessionId()))
    objective: str = ""
    state_tree: StateTree = field(default_factory=StateTree)
    metrics: RuntimeMetrics = field(default_factory=RuntimeMetrics)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_complete: bool = False
    final_result: Optional[MEAResult] = None


# ============================================================================
# Stateful Runtime — The Unified Orchestrator
# ============================================================================


class StatefulRuntime:
    """
    The State-Aware Durable Runtime for Reliable Long-Horizon AI Agents.

    This is the main entry point for the entire system. It integrates
    all seven core components and provides:

        1. Session management with cross-session continuity
        2. Automatic contract enforcement on every action
        3. Governed memory lifecycle with anti-poisoning
        4. Semantics-aware checkpointing at subgoal boundaries
        5. Branch-isolated rollback on failures
        6. Anti-fabrication verification of completion claims
        7. Append-only audit trail for forensic reconstruction

    Usage:
        ```python
        config = RuntimeConfig(
            workspace_dir=Path("./workspace"),
            state_dir=Path("./state"),
            log_dir=Path("./logs"),
        )
        runtime = StatefulRuntime(config)

        # Register behavioral contracts
        contract = BehavioralContract(name="safety")
        contract.add_clause(...)
        runtime.register_contract(contract)

        # Run an agent on a long-horizon task
        result = runtime.run(agent, tool_executor, "Build a web app")
        print(result.success, result.metrics.to_dict())
        ```
    """

    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        config.ensure_dirs()

        # ---- Core Components ----
        self._state_store = StateStore(config.state_dir)
        self._contract_engine = ContractEngine(config.contract_policy)
        self._memory_governor = MemoryGovernor(config.memory_policy)
        self._recovery_engine = RecoveryEngine(
            config.recovery_policy,
            config.state_dir / "checkpoints",
        )
        self._firewall = AntiFabricationFirewall(
            config.firewall_policy,
            config.workspace_dir,
        )

        # ---- Session State ----
        self._session: Optional[RuntimeSession] = None
        self._lineage: Optional[LineageLogger] = None
        self._tracer: Optional[CausalTracer] = None

        logger.info(
            "StatefulRuntime initialized (workspace=%s, state=%s)",
            config.workspace_dir,
            config.state_dir,
        )

    # ---- Properties ----

    @property
    def contract_engine(self) -> ContractEngine:
        return self._contract_engine

    @property
    def memory_governor(self) -> MemoryGovernor:
        return self._memory_governor

    @property
    def recovery_engine(self) -> RecoveryEngine:
        return self._recovery_engine

    @property
    def firewall(self) -> AntiFabricationFirewall:
        return self._firewall

    @property
    def session(self) -> Optional[RuntimeSession]:
        return self._session

    @property
    def lineage(self) -> Optional[LineageLogger]:
        return self._lineage

    # ---- Contract Registration ----

    def register_contract(self, contract: BehavioralContract) -> None:
        """Register a behavioral contract for enforcement during execution."""
        self._contract_engine.register_contract(contract)
        logger.info("Registered contract: %s", contract.name)

    # ---- Main Execution ----

    def run(
        self,
        agent: AgentInterface,
        tool_executor: ToolExecutor,
        objective: str,
        resume_session_id: Optional[str] = None,
    ) -> MEAResult:
        """
        Execute a long-horizon task with full runtime governance.

        This is the primary entry point. It:
        1. Creates or resumes a session
        2. Initializes all component integrations
        3. Runs the MEA loop with contract enforcement
        4. Handles checkpointing and recovery
        5. Verifies completion via anti-fabrication firewall
        6. Returns detailed results with full metrics

        Args:
            agent: The LLM agent implementing AgentInterface.
            tool_executor: Sandboxed tool execution environment.
            objective: The high-level task to accomplish.
            resume_session_id: Optional session ID to resume.

        Returns:
            MEAResult with execution summary and metrics.
        """
        start_time = time.monotonic()

        # ---- Step 1: Initialize Session ----
        if resume_session_id:
            self._resume_session(resume_session_id)
        else:
            self._create_session(objective)

        assert self._session is not None
        assert self._lineage is not None
        assert self._tracer is not None

        logger.info(
            "Runtime: Starting session %s for: %s",
            self._session.session_id,
            objective[:200],
        )

        # ---- Step 2: Build MEA Loop with Component Integrations ----
        mea_loop = MEALoop(self._config)

        # Wire contract engine into MEA loop
        mea_loop.set_pre_action_gate(self._pre_action_gate)
        mea_loop.set_action_monitor(self._action_monitor)

        # Wire lifecycle callbacks
        mea_loop.set_on_subtask_start(self._on_subtask_start)
        mea_loop.set_on_subtask_complete(self._on_subtask_complete)
        mea_loop.set_on_action_complete(self._on_action_complete)
        mea_loop.set_on_audit_complete(self._on_audit_complete)
        mea_loop.set_on_recovery_needed(self._on_recovery_needed)

        # ---- Step 3: Run the MEA Loop ----
        initial_state = tool_executor.get_environment_state()
        tree = StateTree()
        tree.root.state_data = initial_state
        self._session.state_tree = tree

        span = self._tracer.start_span(
            event_type="session_started",
            actor="system",
            payload={"objective": objective},
        )

        result = mea_loop.run(
            agent=agent,
            tool_executor=tool_executor,
            objective=objective,
            initial_state=initial_state,
        )

        # ---- Step 4: Final Completion Verification ----
        if result.success:
            result.completion_verified = self._verify_final_completion(
                objective, result, tool_executor
            )
            if not result.completion_verified:
                result.success = False
                result.error = "Final completion verification failed (anti-fabrication)"
                logger.warning("Runtime: Completion REJECTED by firewall")

        # ---- Step 5: Finalize Session ----
        elapsed = (time.monotonic() - start_time) * 1000
        self._session.metrics.total_time_ms = elapsed
        self._session.metrics.session_id = self._session.session_id
        self._session.is_complete = result.success
        self._session.final_result = result

        # Save final state
        self._state_store.save(self._session.state_tree, self._session.session_id)

        # Emit session end event
        self._tracer.end_span(span, result_payload={
            "success": result.success,
            "total_actions": result.total_actions,
            "total_tokens": result.total_tokens,
            "duration_ms": elapsed,
        }, success=result.success)

        self._lineage.emit(LineageEvent(
            session_id=self._session.session_id,
            event_type="session_ended",
            actor="system",
            payload=result.final_state,
        ))

        # Attach metrics to result
        result.drift_score = self._session.metrics.average_drift_score

        logger.info(
            "Runtime: Session %s %s in %.1fs (%d actions, %d tokens)",
            self._session.session_id,
            "COMPLETED ✓" if result.success else "FAILED ✗",
            elapsed / 1000,
            result.total_actions,
            result.total_tokens,
        )

        return result

    # ---- Session Management ----

    def _create_session(self, objective: str) -> None:
        """Create a new runtime session."""
        session = RuntimeSession(objective=objective)
        self._session = session
        self._lineage = LineageLogger(self._config.log_dir, session.session_id)
        self._tracer = CausalTracer(self._lineage)
        logger.info("Created new session: %s", session.session_id)

    def _resume_session(self, session_id: str) -> None:
        """Resume an existing session from saved state."""
        tree = self._state_store.load(session_id)
        session = RuntimeSession(
            session_id=session_id,
            state_tree=tree,
        )
        self._session = session
        self._lineage = LineageLogger(self._config.log_dir, session_id)
        self._tracer = CausalTracer(self._lineage)

        # Restore memory state from checkpoint if available
        latest_ckpt = self._recovery_engine.checkpoint_manager.get_latest()
        if latest_ckpt is not None:
            mem_snap = latest_ckpt.memory_snapshot
            if mem_snap:
                self._memory_governor.from_checkpoint(mem_snap)

        logger.info("Resumed session: %s (%d nodes)", session_id, tree.total_nodes)

    def list_sessions(self) -> list[str]:
        """List all saved session IDs."""
        return self._state_store.list_sessions()

    # ---- Component Integration Callbacks ----

    def _pre_action_gate(
        self, action: ActionProposal, state: dict[str, Any]
    ) -> tuple[ActionVerdict, list[str]]:
        """
        Pre-action contract enforcement gate.

        Every action proposed by the LLM must pass this gate before
        execution. The ContractEngine evaluates preconditions, forbidden
        actions, and drift state.
        """
        assert self._session is not None

        verdict, reasons = self._contract_engine.evaluate_proposal(action, state)
        self._session.metrics.total_contract_checks += 1

        if verdict == ActionVerdict.BLOCK:
            self._session.metrics.actions_blocked += 1
            if self._lineage:
                self._lineage.emit(LineageEvent(
                    session_id=self._session.session_id,
                    event_type="action_blocked",
                    actor="governor",
                    payload={"action_id": action.action_id, "reasons": reasons},
                    severity="warning",
                ))
        elif verdict == ActionVerdict.REWRITE:
            self._session.metrics.actions_rewritten += 1

        return verdict, reasons

    def _action_monitor(
        self, state: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Action-time invariant monitoring via ContractEngine."""
        ok, violations = self._contract_engine.monitor_execution(state)
        if not ok and self._session:
            self._session.metrics.hard_violations += len(violations)
        return ok, violations

    def _on_subtask_start(self, subtask: SubtaskContract) -> None:
        """Called when a new subtask begins execution."""
        assert self._session is not None

        self._session.metrics.total_subtasks += 1

        # Grow the state tree
        self._session.state_tree.grow(subtask)

        # Create checkpoint at subtask boundary
        if self._config.recovery_policy.enable_auto_checkpoint:
            self._create_checkpoint()

        if self._lineage:
            self._lineage.emit(LineageEvent(
                session_id=self._session.session_id,
                event_type="subtask_started",
                actor="manager",
                node_id=str(self._session.state_tree.active_node_id),
                payload={"objective": subtask.objective},
            ))

    def _on_subtask_complete(self, result: Any) -> None:
        """Called when a subtask is successfully completed and verified."""
        assert self._session is not None

        self._session.metrics.successful_subtasks += 1

        # Mark the active node as verified and compress
        active_node = self._session.state_tree.get_active_node()
        active_node.mark_verified()
        self._session.state_tree.compress(active_node.node_id)
        self._session.state_tree.maintain(active_node.node_id)

        # Memory tick — apply decay and garbage collection
        self._memory_governor.tick()

        # Update drift metrics
        drift_status = self._contract_engine.get_drift_status()
        current_drift = drift_status.get("current_drift", 0.0)
        self._session.metrics.average_drift_score = current_drift
        if current_drift > self._session.metrics.peak_drift_score:
            self._session.metrics.peak_drift_score = current_drift

        if self._lineage:
            self._lineage.emit(LineageEvent(
                session_id=self._session.session_id,
                event_type="subtask_completed",
                actor="auditor",
                node_id=str(active_node.node_id),
                payload={"drift_score": current_drift},
            ))

    def _on_action_complete(
        self, action: ActionProposal, result: ActionResult
    ) -> None:
        """Called after each individual action is executed."""
        assert self._session is not None

        self._session.metrics.total_actions += 1
        self._session.metrics.total_tokens += result.tokens_used

        # Record action in the state tree
        active_node = self._session.state_tree.get_active_node()
        active_node.add_action(action.to_dict(), result.to_dict())

        # Govern memory writes — extract and validate learnings
        if result.success and result.output:
            memory_entry = MemoryEntry(
                tier=MemoryTier.EPISODIC,
                content=f"Action '{action.tool_name}': {result.output[:500]}",
                source_action_id=action.action_id,
                source_node_id=str(active_node.node_id),
            )
            verdict, reason = self._memory_governor.write(memory_entry)
            self._session.metrics.memory_writes += 1
            if verdict == MemoryVerdict.REJECT:
                self._session.metrics.memory_rejections += 1
            elif verdict == MemoryVerdict.QUARANTINE:
                self._session.metrics.memory_quarantines += 1

        # Post-action contract audit
        pre_state = active_node.state_data
        post_state = {**pre_state, **result.state_diff}
        audit_verdict, audit_reasons = self._contract_engine.audit_result(
            action, result, pre_state, post_state
        )

        if audit_verdict == ActionVerdict.BLOCK:
            self._session.metrics.hard_violations += 1
            if self._lineage:
                self._lineage.emit(LineageEvent(
                    session_id=self._session.session_id,
                    event_type="contract_violated",
                    actor="governor",
                    node_id=str(active_node.node_id),
                    payload={
                        "action_id": action.action_id,
                        "violations": audit_reasons,
                    },
                    severity="error",
                ))

        # Log the action
        if self._lineage:
            self._lineage.emit(LineageEvent(
                session_id=self._session.session_id,
                event_type="action_executed" if result.success else "action_failed",
                actor="executor",
                node_id=str(active_node.node_id),
                payload={
                    "action_id": action.action_id,
                    "tool": action.tool_name,
                    "success": result.success,
                },
            ))

    def _on_audit_complete(
        self, result: Any, verified: bool, summary: str
    ) -> None:
        """Called after the Auditor verifies a subtask result."""
        assert self._session is not None

        if not verified:
            self._session.metrics.failed_subtasks += 1

            if self._lineage:
                self._lineage.emit(LineageEvent(
                    session_id=self._session.session_id,
                    event_type="subtask_failed",
                    actor="auditor",
                    payload={"audit_summary": summary[:500]},
                    severity="warning",
                ))

    def _on_recovery_needed(
        self, subtask_result: Any
    ) -> tuple[RecoveryStrategy, dict[str, Any]]:
        """
        Determine recovery strategy when a subtask fails.

        Delegates to the RecoveryEngine which considers:
        - Self-consistency monitoring (loop detection)
        - Checkpoint availability
        - Retry count
        - Drift state
        """
        assert self._session is not None

        failure_info = {
            "action": {},
            "error": getattr(subtask_result, "failure_reason", "Unknown"),
        }

        strategy, context = self._recovery_engine.on_failure(
            action=failure_info.get("action", {}),
            error=failure_info.get("error", ""),
            current_state=self._session.state_tree.get_active_node().state_data,
        )

        self._session.metrics.total_failures += 1

        if strategy == RecoveryStrategy.ROLLBACK:
            self._session.metrics.rollbacks += 1
            # Revise the state tree — isolate failed branch
            active_id = self._session.state_tree.active_node_id
            try:
                new_node = self._session.state_tree.revise(active_id)
                context["restored_state"] = new_node.state_data
                self._session.metrics.successful_recoveries += 1
                self._session.metrics.revisions += 1
            except (KeyError, ValueError) as e:
                logger.error("Recovery: Rollback failed: %s", e)
                strategy = RecoveryStrategy.ABORT

        if self._lineage:
            self._lineage.emit(LineageEvent(
                session_id=self._session.session_id,
                event_type="recovery_initiated",
                actor="recovery",
                payload={
                    "strategy": strategy.name,
                    "error": failure_info.get("error", ""),
                },
                severity="warning",
            ))

        # Update recovery rate
        if self._session.metrics.total_failures > 0:
            self._session.metrics.recovery_rate = (
                self._session.metrics.successful_recoveries
                / self._session.metrics.total_failures
            )

        return strategy, context

    # ---- Checkpointing ----

    def _create_checkpoint(self) -> None:
        """Create a checkpoint at the current state."""
        assert self._session is not None

        try:
            self._recovery_engine.checkpoint_manager.create_checkpoint(
                session_id=self._session.session_id,
                node_id=str(self._session.state_tree.active_node_id),
                state_tree=self._session.state_tree.to_checkpoint(),
                memory_state=self._memory_governor.to_checkpoint(),
                workspace_dir=self._config.workspace_dir,
                contract_state=self._contract_engine.get_drift_status(),
            )
            self._session.metrics.checkpoint_count += 1

            if self._lineage:
                self._lineage.emit(LineageEvent(
                    session_id=self._session.session_id,
                    event_type="checkpoint_created",
                    actor="recovery",
                    node_id=str(self._session.state_tree.active_node_id),
                ))
        except Exception as e:
            logger.error("Failed to create checkpoint: %s", e)

    # ---- Final Completion Verification ----

    def _verify_final_completion(
        self,
        objective: str,
        result: MEAResult,
        tool_executor: ToolExecutor,
    ) -> bool:
        """
        Verify the final completion claim via anti-fabrication firewall.

        The agent's claim of task completion must be independently
        verified against the actual environment state before the
        runtime accepts it as genuine.
        """
        assert self._session is not None

        claim = CompletionClaim(
            subtask_id="final",
            claimed_artifacts=list(result.final_state.keys()),
            claimed_evidence=result.final_state,
            agent_confidence=1.0 if result.success else 0.0,
        )

        env_state = tool_executor.get_environment_state()
        verification = self._firewall.verify_claim(claim, env_state)

        self._session.metrics.completion_claims += 1
        if verification.verdict == CompletionVerdict.GENUINE:
            self._session.metrics.genuine_completions += 1
        elif verification.verdict == CompletionVerdict.FABRICATED:
            self._session.metrics.fabricated_completions += 1

        if self._lineage:
            self._lineage.emit(LineageEvent(
                session_id=self._session.session_id,
                event_type=(
                    "completion_verified"
                    if verification.verdict == CompletionVerdict.GENUINE
                    else "completion_rejected"
                ),
                actor="firewall",
                payload={
                    "verdict": verification.verdict.name,
                    "confidence": verification.confidence,
                    "passed": verification.passed_count,
                    "failed": verification.failed_count,
                },
                severity="info" if verification.verdict == CompletionVerdict.GENUINE else "error",
            ))

        return self._firewall.is_completion_allowed(verification)

    # ---- Metrics & Inspection ----

    def get_metrics(self) -> RuntimeMetrics:
        """Get current session metrics."""
        if self._session is None:
            return RuntimeMetrics()

        # Update compliance rate
        m = self._session.metrics
        if m.total_contract_checks > 0:
            m.compliance_rate = 1.0 - (
                (m.hard_violations + m.soft_violations) / m.total_contract_checks
            )

        return m

    def get_state_tree_stats(self) -> dict[str, Any]:
        """Get state tree statistics for the current session."""
        if self._session is None:
            return {}
        return self._session.state_tree.get_stats()

    def get_memory_stats(self) -> dict[str, Any]:
        """Get memory governor statistics."""
        return self._memory_governor.get_stats()

    def get_lineage_summary(self) -> dict[str, Any]:
        """Get lineage log summary for the current session."""
        if self._lineage is None:
            return {}
        return self._lineage.get_session_summary()

    def export_lineage_graph(self) -> dict[str, Any]:
        """Export the causal lineage graph for visualization."""
        if self._lineage is None:
            return {"nodes": [], "edges": []}
        return self._lineage.export_graph()
