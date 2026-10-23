"""
Comprehensive tests for the State-Aware Durable Runtime.

Tests cover all seven core components individually and integrated:
    1. StateStore & StateTree (MAGE operations)
    2. Behavioral Contracts (drift monitoring, three-stage pipeline)
    3. Memory Governor (write validation, decay, lifecycle)
    4. Recovery Engine (checkpointing, rollback, consistency)
    5. Anti-Fabrication Firewall (completion verification)
    6. Lineage Logger (append-only audit trail)
    7. MEA Loop & Runtime (full integration)
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# ============================================================================
# Imports
# ============================================================================

from state_aware_runtime.config import (
    ActionProposal,
    ActionResult,
    ActionVerdict,
    CompletionVerdict,
    ContractPolicy,
    DriftSeverity,
    FirewallPolicy,
    MemoryPolicy,
    MemoryTier,
    MemoryVerdict,
    NodeId,
    RecoveryPolicy,
    RecoveryStrategy,
    RuntimeConfig,
    SessionId,
    StatePhase,
    SubtaskContract,
    generate_id,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for tests."""
    d = tempfile.mkdtemp(prefix="sadr_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def config(tmp_dir):
    """Create a test runtime config."""
    return RuntimeConfig(
        workspace_dir=tmp_dir / "workspace",
        state_dir=tmp_dir / "state",
        log_dir=tmp_dir / "logs",
    )


# ============================================================================
# Test 1: Config & Types
# ============================================================================


class TestConfig:
    """Test configuration and shared types."""

    def test_generate_id(self):
        id1 = generate_id("test")
        id2 = generate_id("test")
        assert id1.startswith("test_")
        assert id2.startswith("test_")
        assert id1 != id2

    def test_session_id(self):
        sid = SessionId()
        assert str(sid).startswith("sess_")

    def test_action_proposal_to_dict(self):
        ap = ActionProposal(
            action_type="tool_call",
            tool_name="bash",
            parameters={"command": "ls"},
            rationale="List files",
        )
        d = ap.to_dict()
        assert d["action_type"] == "tool_call"
        assert d["tool_name"] == "bash"
        assert d["parameters"]["command"] == "ls"

    def test_subtask_contract(self):
        sc = SubtaskContract(
            objective="Build something",
            preconditions=["env ready"],
            postconditions=["thing built"],
            max_actions=10,
        )
        d = sc.to_dict()
        assert d["objective"] == "Build something"
        assert d["max_actions"] == 10

    def test_runtime_config_defaults(self):
        rc = RuntimeConfig()
        assert rc.contract_policy.max_drift_score == 0.27
        assert rc.memory_policy.enable_write_validation is True
        assert rc.recovery_policy.enable_auto_checkpoint is True
        assert rc.firewall_policy.require_environment_verification is True

    def test_ensure_dirs(self, tmp_dir):
        rc = RuntimeConfig(
            workspace_dir=tmp_dir / "ws",
            state_dir=tmp_dir / "st",
            log_dir=tmp_dir / "lg",
        )
        rc.ensure_dirs()
        assert (tmp_dir / "ws").is_dir()
        assert (tmp_dir / "st").is_dir()
        assert (tmp_dir / "lg").is_dir()


# ============================================================================
# Test 2: State Store & State Tree
# ============================================================================


class TestStateTree:
    """Test Hierarchical State Trees (MAGE operations)."""

    def _make_tree(self, initial_state=None):
        from state_aware_runtime.state_store import StateTree
        tree = StateTree()
        if initial_state:
            tree.root.state_data = initial_state
        return tree

    def test_create_tree(self):
        tree = self._make_tree({"key": "value"})
        assert tree.root is not None
        assert tree.root.state_data["key"] == "value"
        assert tree.total_nodes == 1

    def test_grow(self):
        tree = self._make_tree({"workspace": "ready"})
        subtask = SubtaskContract(objective="Build module A")
        node = tree.grow(subtask)

        assert node.phase == StatePhase.ACTIVE
        assert node.subtask.objective == "Build module A"
        assert node.state_data["workspace"] == "ready"  # Inherited from parent
        assert node.depth == 1
        assert tree.total_nodes == 2
        assert tree.active_node_id == node.node_id

    def test_grow_multiple(self):
        tree = self._make_tree({})
        n1 = tree.grow(SubtaskContract(objective="Task 1"))
        n1.mark_verified()
        n2 = tree.grow(SubtaskContract(objective="Task 2"), parent_id=tree.root.node_id)

        assert tree.total_nodes == 3
        assert len(tree.root.children) == 2

    def test_compress(self):
        tree = self._make_tree({})
        node = tree.grow(SubtaskContract(objective="Build it"))
        node.add_action({"tool_name": "bash"}, {"success": True})
        node.add_action({"tool_name": "write"}, {"success": True})
        node.mark_verified()

        summary = tree.compress(node.node_id)
        assert node.phase == StatePhase.COMPRESSED
        assert len(node.action_trace) == 0  # Raw trace discarded
        assert node.summary != ""

    def test_maintain(self):
        tree = self._make_tree({"x": 1})
        node = tree.grow(SubtaskContract(objective="Do something"))
        node.mark_verified()
        tree.compress(node.node_id, summary="Did something successfully")

        valid = tree.maintain(node.node_id)
        assert valid is True

    def test_maintain_empty_summary(self):
        tree = self._make_tree({"x": 1})
        node = tree.grow(SubtaskContract(objective="Do something"))
        node.mark_verified()
        tree.compress(node.node_id, summary="   ")

        valid = tree.maintain(node.node_id)
        assert valid is False  # Empty summary fails validation

    def test_revise(self):
        tree = self._make_tree({"clean": True})
        failed_node = tree.grow(SubtaskContract(objective="Fail here"))
        failed_node.error_info = "Something went wrong"

        fresh_node = tree.revise(failed_node.node_id)

        assert failed_node.phase == StatePhase.FAILED
        assert failed_node.is_active_path is False
        assert fresh_node.phase == StatePhase.ACTIVE
        assert "REVISED" in fresh_node.subtask.objective
        assert tree.active_node_id == fresh_node.node_id

    def test_get_active_path(self):
        tree = self._make_tree({})
        n1 = tree.grow(SubtaskContract(objective="L1"))
        n1.mark_verified()
        n2 = tree.grow(SubtaskContract(objective="L2"))

        path = tree.get_active_path()
        assert len(path) == 3  # root -> n1 -> n2

    def test_get_context_view(self):
        tree = self._make_tree({"initial": True})
        n1 = tree.grow(SubtaskContract(objective="Sub 1"))
        n1.mark_verified()
        tree.compress(n1.node_id, summary="Sub 1 done")
        tree.grow(SubtaskContract(objective="Sub 2"))

        view = tree.get_context_view()
        assert "canonical_state" in view
        assert "completed_work" in view or "completed_summaries" in view
        assert "current_subtask" in view or "active_subtask" in view

    def test_get_failed_branches(self):
        tree = self._make_tree({})
        n1 = tree.grow(SubtaskContract(objective="Fail"))
        n1.mark_failed("error")

        failed = tree.get_failed_branches()
        assert len(failed) >= 1

    def test_state_diff(self):
        tree = self._make_tree({"a": 1, "b": 2})
        n1 = tree.grow(SubtaskContract(objective="Change state"))
        n1.state_data = {"a": 1, "b": 3, "c": 4}  # modified b, added c

        diff = tree.get_state_diff(tree.root.node_id, n1.node_id)
        assert "c" in diff["added"]
        assert "b" in diff["modified"]

    def test_checkpoint_roundtrip(self):
        from state_aware_runtime.state_store import StateTree

        tree = self._make_tree({"test": True})
        tree.grow(SubtaskContract(objective="Node 1"))
        tree.grow(SubtaskContract(objective="Node 2"), parent_id=tree.root.node_id)

        ckpt = tree.to_checkpoint()
        restored = StateTree.from_checkpoint(ckpt)

        assert restored.total_nodes == tree.total_nodes

    def test_stats(self):
        tree = self._make_tree({})
        tree.grow(SubtaskContract(objective="Task"))

        stats = tree.get_stats()
        assert stats["total_nodes"] == 2
        assert "phase_counts" in stats


class TestStateStore:
    """Test state persistence."""

    def test_save_and_load(self, tmp_dir):
        from state_aware_runtime.state_store import StateStore, StateTree

        store = StateStore(tmp_dir / "states")
        tree = StateTree()
        tree.root.state_data = {"persistent": True}
        tree.grow(SubtaskContract(objective="Persisted task"))

        path = store.save(tree, "test_session")
        assert path.exists()

        loaded = store.load("test_session")
        assert loaded.total_nodes == 2

    def test_list_sessions(self, tmp_dir):
        from state_aware_runtime.state_store import StateStore, StateTree

        store = StateStore(tmp_dir / "states")
        store.save(StateTree(), "s1")
        store.save(StateTree(), "s2")

        sessions = store.list_sessions()
        assert "s1" in sessions
        assert "s2" in sessions

    def test_delete_session(self, tmp_dir):
        from state_aware_runtime.state_store import StateStore, StateTree

        store = StateStore(tmp_dir / "states")
        store.save(StateTree(), "to_delete")
        assert store.delete("to_delete") is True
        assert store.delete("nonexistent") is False


# ============================================================================
# Test 3: Behavioral Contracts
# ============================================================================


class TestContracts:
    """Test runtime behavioral contract enforcement."""

    def test_contract_clause(self):
        from state_aware_runtime.contracts import ContractClause

        clause = ContractClause(
            clause_type="precondition",
            description="Workspace must exist",
            check_fn=lambda state: state.get("workspace_exists", False),
            severity="hard",
        )
        assert clause.check_fn({"workspace_exists": True}) is True
        assert clause.check_fn({"workspace_exists": False}) is False

    def test_behavioral_contract(self):
        from state_aware_runtime.contracts import BehavioralContract, ContractClause

        contract = BehavioralContract(name="safety_contract")
        contract.add_clause(ContractClause(
            clause_type="invariant",
            description="No file deletion",
            check_fn=lambda state: state.get("files_deleted", 0) == 0,
            severity="hard",
        ))
        contract.add_clause(ContractClause(
            clause_type="precondition",
            description="API key set",
            check_fn=lambda state: "api_key" in state,
            severity="soft",
        ))

        inv_results = contract.check_invariants({"files_deleted": 0})
        assert all(passed for _, passed in inv_results)

        pre_results = contract.check_preconditions({"api_key": "xxx"})
        assert all(passed for _, passed in pre_results)

    def test_drift_monitor(self):
        from state_aware_runtime.contracts import DriftMonitor

        monitor = DriftMonitor(window_size=5, threshold=0.27)
        assert monitor.current_drift() == 0.0
        assert monitor.is_within_bounds() is True

    def test_contract_engine_approve(self):
        from state_aware_runtime.contracts import ContractEngine

        engine = ContractEngine(ContractPolicy())
        action = ActionProposal(action_type="tool_call", tool_name="ls")
        verdict, reasons = engine.evaluate_proposal(action, {"safe": True})
        assert verdict == ActionVerdict.APPROVE

    def test_contract_engine_with_contract(self):
        from state_aware_runtime.contracts import (
            BehavioralContract,
            ContractClause,
            ContractEngine,
        )

        engine = ContractEngine(ContractPolicy())
        contract = BehavioralContract(name="test")
        contract.add_clause(ContractClause(
            clause_type="forbidden",
            description="No rm -rf",
            check_fn=lambda state: "rm -rf" not in str(state.get("_action_params", {})),
            severity="hard",
        ))
        engine.register_contract(contract)

        # Safe action
        safe_action = ActionProposal(tool_name="ls", parameters={})
        verdict, _ = engine.evaluate_proposal(safe_action, {})
        assert verdict == ActionVerdict.APPROVE


# ============================================================================
# Test 4: Memory Governor
# ============================================================================


class TestMemoryGovernor:
    """Test memory lifecycle governance."""

    def _make_entry(self, tier=MemoryTier.EPISODIC, content="test obs"):
        from state_aware_runtime.memory_governor import MemoryEntry
        return MemoryEntry(
            tier=tier,
            content=content,
            source_action_id="act_123",
            source_node_id="node_456",
        )

    def test_memory_entry_creation(self):
        entry = self._make_entry()
        assert entry.tier == MemoryTier.EPISODIC
        assert entry.confidence == 1.0
        assert entry.is_quarantined is False

    def test_memory_entry_decay(self):
        entry = self._make_entry()
        entry.decay(0.1)
        assert entry.confidence == pytest.approx(0.9, abs=0.01)

    def test_memory_write_validation(self):
        from state_aware_runtime.memory_governor import MemoryGovernor

        governor = MemoryGovernor(MemoryPolicy())
        entry = self._make_entry(content="Normal observation about the task")
        verdict, reason = governor.write(entry)
        assert verdict == MemoryVerdict.ACCEPT

    def test_memory_read(self):
        from state_aware_runtime.memory_governor import MemoryGovernor

        governor = MemoryGovernor(MemoryPolicy())
        governor.write(self._make_entry(
            tier=MemoryTier.SEMANTIC,
            content="The API endpoint is /api/v2/users",
        ))

        results = governor.read("API endpoint")
        assert len(results) > 0

    def test_memory_tick_decay(self):
        from state_aware_runtime.memory_governor import MemoryGovernor

        governor = MemoryGovernor(MemoryPolicy(episodic_decay_rate=0.5))
        governor.write(self._make_entry(content="Ephemeral observation"))

        # Apply aggressive decay multiple times
        for _ in range(20):
            governor.tick()

        stats = governor.get_stats()
        assert isinstance(stats, dict)

    def test_memory_canonical_state(self):
        from state_aware_runtime.memory_governor import MemoryGovernor

        governor = MemoryGovernor(MemoryPolicy())
        governor.write(self._make_entry(
            tier=MemoryTier.CANONICAL,
            content="Ground truth: server runs on port 8080",
        ))

        canonical = governor.get_canonical_state()
        assert len(canonical) > 0

    def test_memory_checkpoint_roundtrip(self):
        from state_aware_runtime.memory_governor import MemoryGovernor

        gov = MemoryGovernor(MemoryPolicy())
        gov.write(self._make_entry(
            tier=MemoryTier.SEMANTIC,
            content="Test memory for checkpoint",
        ))

        ckpt = gov.to_checkpoint()
        assert "memories" in ckpt

        gov2 = MemoryGovernor(MemoryPolicy())
        gov2.from_checkpoint(ckpt)
        assert len(gov2.memories) == len(gov.memories)


# ============================================================================
# Test 5: Recovery Engine
# ============================================================================


class TestRecovery:
    """Test checkpointing, rollback, and recovery."""

    def test_checkpoint_create_and_restore(self, tmp_dir):
        from state_aware_runtime.recovery import CheckpointManager

        mgr = CheckpointManager(RecoveryPolicy(), tmp_dir / "ckpts")
        ckpt = mgr.create_checkpoint(
            session_id="s1",
            node_id="n1",
            state_tree={"root": "data"},
            memory_state={"memories": []},
            workspace_dir=tmp_dir,
            contract_state={"drift": 0.1},
        )

        assert ckpt.session_id == "s1"
        assert ckpt.node_id == "n1"

        restored = mgr.restore_checkpoint(ckpt.checkpoint_id.value)
        assert restored.session_id == "s1"

    def test_checkpoint_get_latest(self, tmp_dir):
        from state_aware_runtime.recovery import CheckpointManager

        mgr = CheckpointManager(RecoveryPolicy(), tmp_dir / "ckpts")
        mgr.create_checkpoint("s1", "n1", {}, {}, tmp_dir, {})
        mgr.create_checkpoint("s1", "n2", {}, {}, tmp_dir, {})

        latest = mgr.get_latest()
        assert latest is not None
        assert latest.node_id == "n2"

    def test_self_consistency_loop_detection(self):
        from state_aware_runtime.recovery import SelfConsistencyMonitor

        monitor = SelfConsistencyMonitor()
        # Simulate repetitive loop — must use action_type or tool_name keys
        for _ in range(10):
            monitor.record_step(
                action={"action_type": "tool_call", "tool_name": "bash", "parameters": {"cmd": "ls"}},
                result={"output": "file.txt"},
                state={"files": 1},
            )

        has_loop = monitor.detect_loops(window=5)
        assert has_loop is True

    def test_self_consistency_no_loop(self):
        from state_aware_runtime.recovery import SelfConsistencyMonitor

        monitor = SelfConsistencyMonitor()
        # Different action types each time — no loops
        action_types = ["file_write", "shell_exec", "api_call", "file_read", "search"]
        for i, at in enumerate(action_types):
            monitor.record_step(
                action={"action_type": at, "tool_name": at, "parameters": {"i": i}},
                result={"output": f"result_{i}"},
                state={"step": i},
            )

        has_loop = monitor.detect_loops(window=5)
        assert has_loop is False

    def test_recovery_strategy_selection(self, tmp_dir):
        from state_aware_runtime.recovery import RecoveryEngine

        engine = RecoveryEngine(RecoveryPolicy(), tmp_dir / "ckpts")
        strategy, context = engine.on_failure(
            action={"tool": "bash"},
            error="Command failed",
            current_state={"x": 1},
        )

        # First failure should suggest RETRY
        assert strategy == RecoveryStrategy.RETRY


# ============================================================================
# Test 6: Anti-Fabrication Firewall
# ============================================================================


class TestFirewall:
    """Test anti-fabrication completion verification."""

    def test_completion_claim(self):
        from state_aware_runtime.firewall import CompletionClaim

        claim = CompletionClaim(
            subtask_id="sub_1",
            claimed_artifacts=["output.txt"],
            claimed_evidence={"status": "done"},
            agent_confidence=0.95,
        )
        assert claim.agent_confidence == 0.95

    def test_firewall_verify_claim(self, tmp_dir):
        from state_aware_runtime.firewall import (
            AntiFabricationFirewall,
            CompletionClaim,
        )

        firewall = AntiFabricationFirewall(FirewallPolicy(), tmp_dir)
        claim = CompletionClaim(
            subtask_id="sub_1",
            claimed_artifacts=[],
            claimed_evidence={"status": "complete"},
            agent_confidence=0.9,
        )

        result = firewall.verify_claim(claim, {"status": "complete"})
        assert result.verdict in (
            CompletionVerdict.GENUINE,
            CompletionVerdict.INCOMPLETE,
            CompletionVerdict.UNVERIFIABLE,
        )

    def test_artifact_hashing(self, tmp_dir):
        from state_aware_runtime.firewall import AntiFabricationFirewall

        firewall = AntiFabricationFirewall(FirewallPolicy(), tmp_dir)

        # Create a test file
        test_file = tmp_dir / "test.txt"
        test_file.write_text("hello world")

        hashes = firewall.compute_artifact_hashes([test_file])
        assert len(hashes) > 0


# ============================================================================
# Test 7: Lineage Logger
# ============================================================================


class TestLineage:
    """Test append-only audit trail."""

    def test_emit_event(self, tmp_dir):
        from state_aware_runtime.lineage import LineageEvent, LineageLogger

        log = LineageLogger(tmp_dir / "logs", "test_session")
        log.emit(LineageEvent(
            event_type="action_proposed",
            actor="executor",
            payload={"tool": "bash"},
        ))

        assert log.event_count >= 2  # session_started + our event

    def test_query_events(self, tmp_dir):
        from state_aware_runtime.lineage import LineageEvent, LineageLogger

        log = LineageLogger(tmp_dir / "logs", "test_session")
        log.emit(LineageEvent(event_type="action_proposed", actor="executor"))
        log.emit(LineageEvent(event_type="action_blocked", actor="governor"))
        log.emit(LineageEvent(event_type="action_proposed", actor="executor"))

        proposed = log.query(event_type="action_proposed")
        assert len(proposed) == 2

        governor_events = log.query(actor="governor")
        assert len(governor_events) == 1

    def test_causal_chain(self, tmp_dir):
        from state_aware_runtime.lineage import LineageEvent, LineageLogger

        log = LineageLogger(tmp_dir / "logs", "test_session")

        e1 = LineageEvent(event_type="action_proposed", actor="executor")
        log.emit(e1)

        e2 = LineageEvent(
            event_type="action_executed",
            actor="executor",
            parent_event_id=e1.event_id,
        )
        log.emit(e2)

        chain = log.get_causal_chain(e2.event_id)
        assert len(chain) == 2
        assert chain[0].event_id == e1.event_id

    def test_session_summary(self, tmp_dir):
        from state_aware_runtime.lineage import LineageEvent, LineageLogger

        log = LineageLogger(tmp_dir / "logs", "test_session")
        for _ in range(5):
            log.emit(LineageEvent(event_type="action_executed", actor="executor"))

        summary = log.get_session_summary()
        assert summary["total_events"] >= 6  # session_started + 5 actions
        assert "event_types" in summary

    def test_export_graph(self, tmp_dir):
        from state_aware_runtime.lineage import LineageEvent, LineageLogger

        log = LineageLogger(tmp_dir / "logs", "test_session")
        e1 = LineageEvent(event_type="action_proposed", actor="executor")
        log.emit(e1)
        log.emit(LineageEvent(
            event_type="action_executed",
            actor="executor",
            parent_event_id=e1.event_id,
        ))

        graph = log.export_graph()
        assert len(graph["nodes"]) >= 3
        assert len(graph["edges"]) >= 1

    def test_causal_tracer(self, tmp_dir):
        from state_aware_runtime.lineage import CausalTracer, LineageLogger

        log = LineageLogger(tmp_dir / "logs", "test_session")
        tracer = CausalTracer(log)

        span = tracer.start_span("action_proposed", "executor", payload={"x": 1})
        assert tracer.open_span_count == 1

        tracer.end_span(span, result_payload={"y": 2})
        assert tracer.open_span_count == 0


# ============================================================================
# Test 8: MEA Loop
# ============================================================================


class TestMEALoop:
    """Test the Manage-Execute-Audit loop."""

    def test_manager_create_subtask(self, config):
        from state_aware_runtime.cli import DemoAgent
        from state_aware_runtime.mea_loop import Manager

        manager = Manager(config)
        agent = DemoAgent()
        subtasks = manager.create_subtask(
            agent, "Build something", {"workspace": True}, ""
        )
        assert len(subtasks) > 0
        assert all(s.max_actions > 0 for s in subtasks)

    def test_executor_subtask(self, config):
        from state_aware_runtime.cli import DemoAgent, DemoToolExecutor
        from state_aware_runtime.mea_loop import Executor

        executor = Executor(config)
        agent = DemoAgent()
        tool_exec = DemoToolExecutor(config.workspace_dir)

        subtask = SubtaskContract(
            objective="Step 1: Analyze requirements for 'test'",
            max_actions=5,
        )

        result = executor.execute_subtask(
            agent=agent,
            subtask=subtask,
            context={"canonical_state": {}, "subtask": subtask.to_dict()},
            tool_executor=tool_exec,
        )
        assert result.actions_taken > 0
        assert result.success is True

    def test_auditor_verify(self, config):
        from state_aware_runtime.mea_loop import Auditor, SubtaskResult

        auditor = Auditor(config)
        subtask = SubtaskContract(
            objective="Test task",
            postconditions=["output_exists = true"],
            verification_criteria=["output file present"],
        )
        sub_result = SubtaskResult(subtask=subtask, success=True)

        verified, summary = auditor.audit(
            subtask, sub_result, {"output_exists": True, "output_exists = true": True}
        )
        assert verified is True
        assert "PASS" in summary


# ============================================================================
# Test 9: Full Integration — StatefulRuntime
# ============================================================================


class TestIntegration:
    """Test the full StatefulRuntime integration."""

    def test_demo_run(self, config):
        from state_aware_runtime.cli import DemoAgent, DemoToolExecutor
        from state_aware_runtime.runtime import StatefulRuntime

        runtime = StatefulRuntime(config)
        agent = DemoAgent()
        tool_exec = DemoToolExecutor(config.workspace_dir)

        result = runtime.run(agent, tool_exec, "Build a demo application")

        assert result.total_actions > 0
        assert result.total_tokens > 0
        assert result.total_time_ms > 0

    def test_metrics_available(self, config):
        from state_aware_runtime.cli import DemoAgent, DemoToolExecutor
        from state_aware_runtime.runtime import StatefulRuntime

        runtime = StatefulRuntime(config)
        agent = DemoAgent()
        tool_exec = DemoToolExecutor(config.workspace_dir)

        runtime.run(agent, tool_exec, "Test metrics")

        metrics = runtime.get_metrics()
        assert metrics.total_actions > 0
        assert metrics.session_id != ""

        m_dict = metrics.to_dict()
        assert "drift" in m_dict
        assert "contracts" in m_dict
        assert "recovery" in m_dict
        assert "memory" in m_dict
        assert "anti_fabrication" in m_dict

    def test_session_persistence(self, config):
        from state_aware_runtime.cli import DemoAgent, DemoToolExecutor
        from state_aware_runtime.runtime import StatefulRuntime

        runtime = StatefulRuntime(config)
        agent = DemoAgent()
        tool_exec = DemoToolExecutor(config.workspace_dir)

        runtime.run(agent, tool_exec, "Persistence test")

        sessions = runtime.list_sessions()
        assert len(sessions) > 0

    def test_lineage_recorded(self, config):
        from state_aware_runtime.cli import DemoAgent, DemoToolExecutor
        from state_aware_runtime.runtime import StatefulRuntime

        runtime = StatefulRuntime(config)
        agent = DemoAgent()
        tool_exec = DemoToolExecutor(config.workspace_dir)

        runtime.run(agent, tool_exec, "Lineage test")

        summary = runtime.get_lineage_summary()
        assert summary["total_events"] > 0
        assert "session_started" in summary.get("event_types", {})

    def test_state_tree_stats(self, config):
        from state_aware_runtime.cli import DemoAgent, DemoToolExecutor
        from state_aware_runtime.runtime import StatefulRuntime

        runtime = StatefulRuntime(config)
        agent = DemoAgent()
        tool_exec = DemoToolExecutor(config.workspace_dir)

        runtime.run(agent, tool_exec, "Tree stats test")

        stats = runtime.get_state_tree_stats()
        assert stats["total_nodes"] > 1  # Root + at least one subtask
