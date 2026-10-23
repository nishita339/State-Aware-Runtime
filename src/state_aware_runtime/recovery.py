"""
Checkpoint/Restore & Recovery Engine for State-Aware Durable Runtime.

Provides semantics-aware checkpointing, branch-isolated rollback, self-
consistency monitoring, and orchestrated recovery from detected failures.

Research Foundations:
    - Crab (Wu et al., 2026): Semantics-aware checkpointing that captures
      state-tree snapshots, memory state, and workspace hashes at subgoal
      boundaries, enabling fine-grained rollback without full replay.
    - Rewind-IL (Zheng et al., 2026): Self-consistency monitoring via
      overlapping action-result-state triples.  Detects loops, regressions,
      and incoherent state transitions that signal the agent has gone off
      track.
    - Distributed Speculative Execution (Li et al., 2024): Branch isolation
      and alternative-branch creation, allowing the runtime to speculatively
      fork execution and roll back losing branches cheaply.

Architecture:
    CheckpointManager ──→ Checkpoint (serialisable snapshot)
          ↕
    RollbackEngine ──→ isolate / branch / rollback operations
          ↕
    SelfConsistencyMonitor ──→ loop & regression detection
          ↕
    RecoveryEngine ──→ on_failure → strategy selection → execute_recovery
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from state_aware_runtime.config import (
    CheckpointId,
    RecoveryPolicy,
    RecoveryStrategy,
    StatePhase,
    generate_id,
)

__all__ = [
    "Checkpoint",
    "CheckpointManager",
    "RollbackEngine",
    "SelfConsistencyMonitor",
    "RecoveryEngine",
]

logger = logging.getLogger(__name__)


# ============================================================================
# Checkpoint
# ============================================================================


@dataclass
class Checkpoint:
    """A serialisable state snapshot taken at a state-tree node boundary.

    Captures everything needed to restore agent execution to a prior point:
    the hierarchical state tree, memory store, workspace file hashes, and
    contract-enforcement state.  Based on Crab's semantics-aware checkpoint
    format (Wu et al., 2026).

    Attributes:
        checkpoint_id:       Unique identifier (``CheckpointId`` from config).
        session_id:          The session this checkpoint belongs to.
        node_id:             State-tree node at which the checkpoint was taken.
        created_at:          UTC timestamp of checkpoint creation.
        state_tree_snapshot: Serialised state tree (dict form).
        memory_snapshot:     Serialised memory state from ``MemoryGovernor``.
        workspace_snapshot:  Mapping of file paths → SHA-256 hashes.
        contract_state:      Drift scores, violation counts, etc.
        metadata:            Arbitrary additional metadata.
        size_bytes:          Approximate serialised size in bytes.
    """

    checkpoint_id: CheckpointId = field(default_factory=CheckpointId)
    session_id: str = ""
    node_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state_tree_snapshot: dict[str, Any] = field(default_factory=dict)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    workspace_snapshot: dict[str, str] = field(default_factory=dict)
    contract_state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    size_bytes: int = 0

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the checkpoint to a plain dict for JSON persistence."""
        return {
            "checkpoint_id": str(self.checkpoint_id),
            "session_id": self.session_id,
            "node_id": self.node_id,
            "created_at": self.created_at.isoformat(),
            "state_tree_snapshot": self.state_tree_snapshot,
            "memory_snapshot": self.memory_snapshot,
            "workspace_snapshot": self.workspace_snapshot,
            "contract_state": self.contract_state,
            "metadata": self.metadata,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        """Reconstruct a ``Checkpoint`` from a serialised dict.

        Args:
            data: Dict previously produced by :meth:`to_dict`.

        Returns:
            Restored ``Checkpoint`` instance.
        """
        return cls(
            checkpoint_id=CheckpointId(value=data["checkpoint_id"]),
            session_id=data.get("session_id", ""),
            node_id=data.get("node_id", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            state_tree_snapshot=data.get("state_tree_snapshot", {}),
            memory_snapshot=data.get("memory_snapshot", {}),
            workspace_snapshot=data.get("workspace_snapshot", {}),
            contract_state=data.get("contract_state", {}),
            metadata=data.get("metadata", {}),
            size_bytes=data.get("size_bytes", 0),
        )

    def save(self, path: Path) -> None:
        """Persist this checkpoint to a JSON file.

        Parent directories are created automatically.

        Args:
            path: Filesystem path to write the JSON file to.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, default=str)
        self.size_bytes = len(payload.encode("utf-8"))
        path.write_text(payload, encoding="utf-8")
        logger.info(
            "Checkpoint %s saved to %s (%d bytes)",
            self.checkpoint_id, path, self.size_bytes,
        )

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        """Load a checkpoint from a JSON file.

        Args:
            path: Filesystem path to read.

        Returns:
            Restored ``Checkpoint`` instance.

        Raises:
            FileNotFoundError: If *path* does not exist.
        """
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        ckpt = cls.from_dict(data)
        ckpt.size_bytes = len(raw.encode("utf-8"))
        logger.info("Checkpoint %s loaded from %s", ckpt.checkpoint_id, path)
        return ckpt


# ============================================================================
# CheckpointManager
# ============================================================================


class CheckpointManager:
    """Creates, indexes, and manages state checkpoints.

    Implements Crab-style semantics-aware checkpointing (Wu et al., 2026)
    where snapshots are taken at meaningful subgoal boundaries rather than
    at fixed action intervals alone.

    The manager maintains an in-memory index of all checkpoints and
    persists each to disk as a JSON file.

    Args:
        policy:         The ``RecoveryPolicy`` governing checkpoint limits.
        checkpoint_dir: Filesystem directory where checkpoints are stored.
    """

    def __init__(self, policy: RecoveryPolicy, checkpoint_dir: Path) -> None:
        self._policy = policy
        self._checkpoint_dir = checkpoint_dir
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._index: list[Checkpoint] = []
        self._load_existing_index()
        logger.info(
            "CheckpointManager initialised (dir=%s, existing=%d)",
            checkpoint_dir, len(self._index),
        )

    def _load_existing_index(self) -> None:
        """Scan the checkpoint directory and load the in-memory index."""
        if not self._checkpoint_dir.exists():
            return
        for fp in sorted(self._checkpoint_dir.glob("*.json")):
            try:
                ckpt = Checkpoint.load(fp)
                self._index.append(ckpt)
            except Exception:
                logger.warning("Failed to load checkpoint file %s — skipping", fp)
        self._index.sort(key=lambda c: c.created_at)

    # -- public API --------------------------------------------------------

    def create_checkpoint(
        self,
        session_id: str,
        node_id: str,
        state_tree: dict[str, Any],
        memory_state: dict[str, Any],
        workspace_dir: Optional[Path],
        contract_state: dict[str, Any],
    ) -> Checkpoint:
        """Create a new checkpoint capturing the current runtime state.

        The workspace snapshot is built by hashing every file in
        *workspace_dir* (non-recursively for top-level files, recursively
        for nested directories).  Only SHA-256 hashes are stored, not the
        file contents themselves.

        Args:
            session_id:     Current session ID.
            node_id:        State-tree node at which this checkpoint is taken.
            state_tree:     Serialised state tree dict.
            memory_state:   Serialised memory state dict.
            workspace_dir:  Optional workspace directory for file hashing.
            contract_state: Current contract-enforcement state.

        Returns:
            The newly created ``Checkpoint``.
        """
        workspace_snapshot: dict[str, str] = {}
        if workspace_dir is not None and workspace_dir.exists():
            workspace_snapshot = self._hash_workspace(workspace_dir)

        ckpt = Checkpoint(
            session_id=session_id,
            node_id=node_id,
            state_tree_snapshot=state_tree,
            memory_snapshot=memory_state,
            workspace_snapshot=workspace_snapshot,
            contract_state=contract_state,
            metadata={
                "total_checkpoints_at_creation": len(self._index) + 1,
            },
        )

        filename = f"{ckpt.checkpoint_id}.json"
        ckpt.save(self._checkpoint_dir / filename)
        self._index.append(ckpt)

        # Auto-prune if over limit
        if len(self._index) > self._policy.max_checkpoints:
            self.prune(self._policy.max_checkpoints)

        logger.info(
            "Checkpoint created: %s at node %s (session %s)",
            ckpt.checkpoint_id, node_id, session_id,
        )
        return ckpt

    def restore_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """Load a specific checkpoint by its ID.

        First checks the in-memory index, then falls back to disk.

        Args:
            checkpoint_id: The checkpoint ID string to restore.

        Returns:
            The restored ``Checkpoint``.

        Raises:
            KeyError: If no checkpoint with that ID exists.
        """
        for ckpt in self._index:
            if str(ckpt.checkpoint_id) == checkpoint_id:
                logger.info("Restored checkpoint %s from index", checkpoint_id)
                return ckpt

        # Fallback: attempt disk load
        fp = self._checkpoint_dir / f"{checkpoint_id}.json"
        if fp.exists():
            ckpt = Checkpoint.load(fp)
            self._index.append(ckpt)
            self._index.sort(key=lambda c: c.created_at)
            return ckpt

        raise KeyError(f"Checkpoint '{checkpoint_id}' not found")

    def get_latest(self) -> Optional[Checkpoint]:
        """Return the most recently created checkpoint, or ``None``."""
        if not self._index:
            return None
        return self._index[-1]

    def get_by_node(self, node_id: str) -> Optional[Checkpoint]:
        """Return the most recent checkpoint taken at a given state-tree node.

        Args:
            node_id: The node ID to search for.

        Returns:
            The matching ``Checkpoint``, or ``None``.
        """
        for ckpt in reversed(self._index):
            if ckpt.node_id == node_id:
                return ckpt
        return None

    def list_checkpoints(self) -> list[Checkpoint]:
        """Return all available checkpoints, sorted by creation time."""
        return list(self._index)

    def prune(self, max_count: int) -> None:
        """Remove the oldest checkpoints so that at most *max_count* remain.

        Checkpoint files are deleted from disk as well.

        Args:
            max_count: Maximum number of checkpoints to retain.
        """
        if len(self._index) <= max_count:
            return
        evict_count = len(self._index) - max_count
        evicted = self._index[:evict_count]
        self._index = self._index[evict_count:]
        for ckpt in evicted:
            fp = self._checkpoint_dir / f"{ckpt.checkpoint_id}.json"
            if fp.exists():
                fp.unlink()
                logger.info("Pruned checkpoint file %s", fp)
            logger.info("Pruned checkpoint %s", ckpt.checkpoint_id)

    def compute_state_diff(
        self, ckpt_a: Checkpoint, ckpt_b: Checkpoint,
    ) -> dict[str, Any]:
        """Compute what changed between two checkpoints.

        Compares state-tree snapshots, memory snapshots, workspace hashes,
        and contract state.

        Args:
            ckpt_a: Earlier checkpoint.
            ckpt_b: Later checkpoint.

        Returns:
            Dict describing additions, removals, and modifications per
            category.
        """
        diff: dict[str, Any] = {
            "from_checkpoint": str(ckpt_a.checkpoint_id),
            "to_checkpoint": str(ckpt_b.checkpoint_id),
            "workspace_changes": self._diff_dicts(
                ckpt_a.workspace_snapshot, ckpt_b.workspace_snapshot,
            ),
            "contract_state_changes": self._diff_dicts(
                ckpt_a.contract_state, ckpt_b.contract_state,
            ),
            "state_tree_changed": ckpt_a.state_tree_snapshot != ckpt_b.state_tree_snapshot,
            "memory_changed": ckpt_a.memory_snapshot != ckpt_b.memory_snapshot,
        }
        return diff

    # -- private helpers ---------------------------------------------------

    @staticmethod
    def _hash_workspace(workspace_dir: Path) -> dict[str, str]:
        """Build a dict of relative-path → SHA-256 hash for all files."""
        result: dict[str, str] = {}
        try:
            for root, _dirs, files in os.walk(workspace_dir):
                for fname in files:
                    fpath = Path(root) / fname
                    try:
                        sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
                        rel = str(fpath.relative_to(workspace_dir))
                        result[rel] = sha
                    except (OSError, PermissionError):
                        logger.debug("Skipping unhashable file %s", fpath)
        except Exception as exc:
            logger.warning("Workspace hashing failed: %s", exc)
        return result

    @staticmethod
    def _diff_dicts(
        old: dict[str, Any], new: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute additions, removals, and modifications between two dicts."""
        added = {k: new[k] for k in new if k not in old}
        removed = {k: old[k] for k in old if k not in new}
        modified = {
            k: {"old": old[k], "new": new[k]}
            for k in old
            if k in new and old[k] != new[k]
        }
        return {"added": added, "removed": removed, "modified": modified}


# ============================================================================
# RollbackEngine
# ============================================================================


class RollbackEngine:
    """Handles branch isolation and rollback operations.

    Implements DSE-style branch isolation (Li et al., 2024) where failed
    execution branches are marked and isolated rather than deleted, allowing
    post-hoc analysis.  Alternative branches can be created from any prior
    checkpoint.

    Args:
        checkpoint_manager: The ``CheckpointManager`` providing snapshot access.
    """

    def __init__(self, checkpoint_manager: CheckpointManager) -> None:
        self._ckpt_mgr = checkpoint_manager
        self._rollback_count: int = 0
        self._isolated_branches: list[str] = []

    def rollback_to(self, checkpoint_id: str) -> dict[str, Any]:
        """Roll back to the state captured by a specific checkpoint.

        Args:
            checkpoint_id: The checkpoint to restore.

        Returns:
            Dict containing the restored state components (state tree,
            memory snapshot, contract state) for the caller to apply.

        Raises:
            KeyError: If the checkpoint is not found.
        """
        ckpt = self._ckpt_mgr.restore_checkpoint(checkpoint_id)
        self._rollback_count += 1
        logger.info(
            "Rollback #%d → checkpoint %s (node=%s)",
            self._rollback_count, checkpoint_id, ckpt.node_id,
        )
        return {
            "checkpoint_id": str(ckpt.checkpoint_id),
            "node_id": ckpt.node_id,
            "state_tree_snapshot": ckpt.state_tree_snapshot,
            "memory_snapshot": ckpt.memory_snapshot,
            "contract_state": ckpt.contract_state,
            "workspace_snapshot": ckpt.workspace_snapshot,
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        }

    def isolate_failed_branch(
        self, node_id: str, state_tree: dict[str, Any],
    ) -> dict[str, Any]:
        """Mark a branch rooted at *node_id* as failed and isolate it.

        In the state-tree dict, sets the node's phase to ``FAILED`` and
        adds isolation metadata.  The branch remains in the tree for audit
        purposes but is excluded from active execution.

        Args:
            node_id:    The root node of the failed branch.
            state_tree: The current state-tree dict (mutated and returned).

        Returns:
            The updated state-tree dict.
        """
        self._isolated_branches.append(node_id)

        # Walk the tree and mark the target node + descendants
        self._mark_failed_recursive(node_id, state_tree)

        logger.info("Isolated failed branch at node %s", node_id)
        return state_tree

    def create_alternative_branch(
        self, from_checkpoint: str, new_subtask: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an alternative execution branch from a prior checkpoint.

        Restores state to the checkpoint and attaches a new subtask as an
        alternative branch.

        Args:
            from_checkpoint: Checkpoint ID to branch from.
            new_subtask:     Subtask specification for the alternative branch.

        Returns:
            Dict with restored state and the new branch metadata.

        Raises:
            KeyError: If the checkpoint is not found.
        """
        ckpt = self._ckpt_mgr.restore_checkpoint(from_checkpoint)
        branch_id = generate_id("branch")

        result = {
            "branch_id": branch_id,
            "from_checkpoint": str(ckpt.checkpoint_id),
            "from_node": ckpt.node_id,
            "state_tree_snapshot": ckpt.state_tree_snapshot,
            "memory_snapshot": ckpt.memory_snapshot,
            "contract_state": ckpt.contract_state,
            "new_subtask": new_subtask,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "Created alternative branch %s from checkpoint %s",
            branch_id, from_checkpoint,
        )
        return result

    def get_rollback_candidates(
        self, current_node_id: str, checkpoints: list[Checkpoint],
    ) -> list[Checkpoint]:
        """Find valid rollback targets from the available checkpoints.

        A checkpoint is a valid rollback target if:
        - It was taken before the current node (by creation time).
        - Its node is not in the isolated-branches set.

        Args:
            current_node_id: The currently active node.
            checkpoints:     List of available checkpoints.

        Returns:
            Filtered and sorted list of candidate ``Checkpoint`` objects
            (most recent first).
        """
        candidates = [
            ckpt for ckpt in checkpoints
            if (
                ckpt.node_id != current_node_id
                and ckpt.node_id not in self._isolated_branches
            )
        ]
        # Most recent first
        candidates.sort(key=lambda c: c.created_at, reverse=True)
        return candidates

    # -- private helpers ---------------------------------------------------

    @staticmethod
    def _mark_failed_recursive(
        node_id: str, state_tree: dict[str, Any],
    ) -> None:
        """Recursively mark a node and its children as FAILED.

        Walks the state-tree dict looking for nodes by ``node_id`` field
        and sets their ``phase`` to ``FAILED``.
        """
        # Direct top-level match
        if state_tree.get("node_id") == node_id:
            state_tree["phase"] = StatePhase.FAILED.name
            state_tree["isolated"] = True

        # Recurse into children
        for child in state_tree.get("children", []):
            if isinstance(child, dict):
                if child.get("node_id") == node_id:
                    child["phase"] = StatePhase.FAILED.name
                    child["isolated"] = True
                    # Mark all descendants too
                    RollbackEngine._mark_all_descendants_failed(child)
                else:
                    RollbackEngine._mark_failed_recursive(node_id, child)

    @staticmethod
    def _mark_all_descendants_failed(node: dict[str, Any]) -> None:
        """Mark every descendant of *node* as FAILED."""
        for child in node.get("children", []):
            if isinstance(child, dict):
                child["phase"] = StatePhase.FAILED.name
                child["isolated"] = True
                RollbackEngine._mark_all_descendants_failed(child)


# ============================================================================
# SelfConsistencyMonitor
# ============================================================================


class SelfConsistencyMonitor:
    """Detects when agent execution becomes inconsistent or degenerate.

    Implements Rewind-IL (Zheng et al., 2026) style self-consistency
    monitoring by recording overlapping action-result-state triples and
    checking for:

    1. **Repetitive action loops** — the agent is repeating the same actions
       without making progress.
    2. **State regressions** — a tracked state key reverts to a previous
       value after advancing, suggesting the agent undid its own progress.
    3. **General inconsistency** — recent state transitions that violate
       expected monotonicity or causal ordering.

    Args:
        overlap_window: Number of most-recent steps to keep for overlap
                        analysis (default 3, per Rewind-IL recommendation).
    """

    def __init__(self, overlap_window: int = 3) -> None:
        self._overlap_window = overlap_window
        self._history: list[dict[str, Any]] = []  # each: {action, result, state}

    def record_step(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        """Record an action-result-state triple for consistency tracking.

        Args:
            action: The action that was executed.
            result: The result of executing the action.
            state:  The state observed after execution.
        """
        self._history.append({
            "action": action,
            "result": result,
            "state": state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        logger.debug(
            "SelfConsistencyMonitor recorded step %d", len(self._history),
        )

    def check_consistency(self) -> tuple[bool, Optional[str]]:
        """Check whether recent execution steps are self-consistent.

        Uses the overlap window to compare adjacent triples.  Flags
        inconsistency if the same action on the same state produces
        different results.

        Returns:
            ``(is_consistent, reason)`` — reason is ``None`` when consistent.
        """
        if len(self._history) < 2:
            return True, None

        window = self._history[-self._overlap_window:]

        # Check for identical action+state producing different results
        for i in range(len(window) - 1):
            for j in range(i + 1, len(window)):
                step_i, step_j = window[i], window[j]
                if (
                    step_i["action"] == step_j["action"]
                    and step_i["state"] == step_j["state"]
                    and step_i["result"] != step_j["result"]
                ):
                    reason = (
                        f"Non-determinism detected: identical action+state at "
                        f"steps {len(self._history) - len(window) + i} and "
                        f"{len(self._history) - len(window) + j} produced "
                        f"different results"
                    )
                    logger.warning(reason)
                    return False, reason

        # Check for loops (a special form of inconsistency — no progress)
        if self.detect_loops(window=len(window)):
            reason = (
                f"Action loop detected over last {len(window)} steps — "
                "agent may be stuck"
            )
            logger.warning(reason)
            return False, reason

        return True, None

    def detect_loops(self, window: int = 5) -> bool:
        """Detect repetitive action loops in recent history.

        An action loop is detected when the same action type (and optionally
        same parameters) appears in every step within the window.

        Args:
            window: Number of recent steps to examine.

        Returns:
            ``True`` if a loop is detected.
        """
        if len(self._history) < window:
            return False

        recent = self._history[-window:]
        action_types = [
            step["action"].get("action_type", step["action"].get("tool_name", ""))
            for step in recent
        ]

        # All the same action type → likely loop
        if len(set(action_types)) == 1 and action_types[0]:
            # Further check: are the parameters also identical?
            action_params = [
                json.dumps(step["action"].get("parameters", {}), sort_keys=True)
                for step in recent
            ]
            if len(set(action_params)) == 1:
                logger.warning(
                    "Exact loop detected: action=%s repeated %d times",
                    action_types[0], window,
                )
                return True

            # Even with varying params, same action type repeated is suspect
            logger.info(
                "Potential loop: action_type=%s repeated %d times with varying params",
                action_types[0], window,
            )
            return True

        # Check for short cycles (A→B→A→B…)
        if window >= 4:
            cycle_len = 2
            cycle = action_types[:cycle_len]
            is_cycle = all(
                action_types[i] == cycle[i % cycle_len]
                for i in range(len(action_types))
            )
            if is_cycle and len(set(cycle)) > 1:
                logger.warning("Cycle detected: %s", " → ".join(cycle))
                return True

        return False

    def detect_regression(self, state_key: str) -> bool:
        """Detect if a tracked state key has regressed to a previous value.

        Regression occurs when a state value that had advanced (changed from
        its initial value) later reverts to an earlier observed value.

        Args:
            state_key: The key to monitor across recorded states.

        Returns:
            ``True`` if regression is detected.
        """
        values: list[Any] = []
        for step in self._history:
            state = step.get("state", {})
            if state_key in state:
                values.append(state[state_key])

        if len(values) < 3:
            return False

        # Check if the latest value equals an earlier (non-immediately-prior)
        # value, suggesting the agent reverted its own progress.
        latest = values[-1]
        previous_set = set()
        for v in values[:-2]:  # exclude the immediately prior value
            try:
                # Only hashable values can be tracked this way
                previous_set.add(v)
            except TypeError:
                continue

        try:
            if latest in previous_set and latest != values[-2]:
                logger.warning(
                    "State regression detected for key '%s': "
                    "reverted from %r to earlier value %r",
                    state_key, values[-2], latest,
                )
                return True
        except TypeError:
            pass

        return False


# ============================================================================
# RecoveryEngine
# ============================================================================


class RecoveryEngine:
    """Coordinates failure detection, strategy selection, and recovery execution.

    Integrates ``CheckpointManager``, ``RollbackEngine``, and
    ``SelfConsistencyMonitor`` into a cohesive recovery workflow.  When
    ``on_failure()`` is called, the engine selects the best recovery
    strategy based on the failure type, retry history, and available
    checkpoints, then ``execute_recovery()`` carries out the chosen
    strategy.

    References:
        Crab (Wu et al., 2026), Rewind-IL (Zheng et al., 2026),
        DSE (Li et al., 2024).

    Args:
        policy:         The ``RecoveryPolicy`` governing recovery behaviour.
        checkpoint_dir: Filesystem directory for checkpoint storage.
    """

    def __init__(self, policy: RecoveryPolicy, checkpoint_dir: Path) -> None:
        self._policy = policy
        self._checkpoint_mgr = CheckpointManager(policy, checkpoint_dir)
        self._rollback_engine = RollbackEngine(self._checkpoint_mgr)
        self._consistency_monitor = SelfConsistencyMonitor()

        # Recovery statistics
        self._total_failures: int = 0
        self._successful_recoveries: int = 0
        self._failed_recoveries: int = 0
        self._retry_counts: dict[str, int] = {}  # action_id → retry count
        self._recovery_log: list[dict[str, Any]] = []

        logger.info("RecoveryEngine initialised (dir=%s)", checkpoint_dir)

    # -- properties --------------------------------------------------------

    @property
    def total_failures(self) -> int:
        """Total number of failures encountered."""
        return self._total_failures

    @property
    def successful_recoveries(self) -> int:
        """Total successful recoveries."""
        return self._successful_recoveries

    @property
    def recovery_rate(self) -> float:
        """Fraction of failures successfully recovered (0.0–1.0)."""
        if self._total_failures == 0:
            return 1.0
        return self._successful_recoveries / self._total_failures

    # -- exposed sub-components -------------------------------------------

    @property
    def checkpoint_manager(self) -> CheckpointManager:
        """Access the underlying ``CheckpointManager``."""
        return self._checkpoint_mgr

    @property
    def rollback_engine(self) -> RollbackEngine:
        """Access the underlying ``RollbackEngine``."""
        return self._rollback_engine

    @property
    def consistency_monitor(self) -> SelfConsistencyMonitor:
        """Access the underlying ``SelfConsistencyMonitor``."""
        return self._consistency_monitor

    # -- failure handling --------------------------------------------------

    def on_failure(
        self,
        action: dict[str, Any],
        error: str,
        current_state: dict[str, Any],
    ) -> tuple[RecoveryStrategy, dict[str, Any]]:
        """Determine the appropriate recovery strategy for a failure.

        Strategy selection logic:
        1. If retries remain and the error is transient → ``RETRY``.
        2. If checkpoints exist and branch isolation is enabled → ``ROLLBACK``
           or ``BRANCH``.
        3. If max retries exceeded → ``ESCALATE``.
        4. If no checkpoints and no retries → ``ABORT``.

        Args:
            action:        The action that failed (dict with at least
                           ``action_id`` and ``action_type``).
            error:         Human-readable error description.
            current_state: The state at the time of failure.

        Returns:
            ``(RecoveryStrategy, context)`` where *context* provides data
            needed by :meth:`execute_recovery`.
        """
        self._total_failures += 1
        action_id = action.get("action_id", "unknown")
        retries = self._retry_counts.get(action_id, 0)

        logger.info(
            "Failure #%d on action %s (retries=%d): %s",
            self._total_failures, action_id, retries, error,
        )

        context: dict[str, Any] = {
            "action": action,
            "error": error,
            "current_state": current_state,
            "retry_count": retries,
            "failure_number": self._total_failures,
        }

        # Check for consistency issues first
        is_consistent, reason = self._consistency_monitor.check_consistency()
        if not is_consistent:
            context["consistency_issue"] = reason

        # Strategy 1: RETRY if under limit
        if retries < self._policy.max_retry_attempts:
            self._retry_counts[action_id] = retries + 1
            context["strategy_reason"] = (
                f"Retry {retries + 1}/{self._policy.max_retry_attempts}"
            )
            strategy = RecoveryStrategy.RETRY
            self._log_recovery(strategy, context, decided=True)
            return strategy, context

        # Strategy 2: ROLLBACK if checkpoints exist
        latest_ckpt = self._checkpoint_mgr.get_latest()
        if latest_ckpt is not None and self._policy.enable_branch_isolation:
            # If we've already rolled back recently, try BRANCH instead
            recent_rollbacks = sum(
                1 for entry in self._recovery_log[-5:]
                if entry.get("strategy") == RecoveryStrategy.ROLLBACK.name
            )
            if recent_rollbacks >= 2:
                context["strategy_reason"] = (
                    "Multiple recent rollbacks — trying alternative branch"
                )
                context["from_checkpoint"] = str(latest_ckpt.checkpoint_id)
                strategy = RecoveryStrategy.BRANCH
            else:
                context["strategy_reason"] = "Rolling back to latest checkpoint"
                context["checkpoint_id"] = str(latest_ckpt.checkpoint_id)
                strategy = RecoveryStrategy.ROLLBACK

            self._log_recovery(strategy, context, decided=True)
            return strategy, context

        # Strategy 3: ESCALATE if retries exhausted but checkpoints missing
        if retries >= self._policy.max_retry_attempts:
            context["strategy_reason"] = (
                f"Max retries ({self._policy.max_retry_attempts}) exhausted, "
                "no checkpoints available — escalating"
            )
            strategy = RecoveryStrategy.ESCALATE
            self._log_recovery(strategy, context, decided=True)
            return strategy, context

        # Strategy 4: ABORT as last resort
        context["strategy_reason"] = "No recovery options available — aborting"
        strategy = RecoveryStrategy.ABORT
        self._log_recovery(strategy, context, decided=True)
        return strategy, context

    def execute_recovery(
        self,
        strategy: RecoveryStrategy,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the chosen recovery strategy.

        Args:
            strategy: The ``RecoveryStrategy`` selected by :meth:`on_failure`.
            context:  Context dict from :meth:`on_failure` containing
                      strategy-specific data.

        Returns:
            Dict with recovery results and next-step guidance.
        """
        result: dict[str, Any] = {
            "strategy": strategy.name,
            "success": False,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            if strategy is RecoveryStrategy.RETRY:
                result.update(self._execute_retry(context))
            elif strategy is RecoveryStrategy.ROLLBACK:
                result.update(self._execute_rollback(context))
            elif strategy is RecoveryStrategy.BRANCH:
                result.update(self._execute_branch(context))
            elif strategy is RecoveryStrategy.ESCALATE:
                result.update(self._execute_escalate(context))
            elif strategy is RecoveryStrategy.ABORT:
                result.update(self._execute_abort(context))
            else:
                result["error"] = f"Unknown strategy: {strategy}"

            if result.get("success", False):
                self._successful_recoveries += 1
            else:
                self._failed_recoveries += 1

        except Exception as exc:
            result["success"] = False
            result["error"] = str(exc)
            self._failed_recoveries += 1
            logger.error("Recovery execution failed: %s", exc)

        self._log_recovery(strategy, result, decided=False)
        return result

    # -- strategy implementations ------------------------------------------

    def _execute_retry(self, context: dict[str, Any]) -> dict[str, Any]:
        """Prepare for retrying the failed action."""
        return {
            "success": True,
            "action": "retry",
            "retry_count": context.get("retry_count", 0),
            "instruction": "Re-execute the failed action with current state",
            "action_to_retry": context.get("action", {}),
        }

    def _execute_rollback(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute a rollback to the specified checkpoint."""
        checkpoint_id = context.get("checkpoint_id", "")
        if not checkpoint_id:
            return {"success": False, "error": "No checkpoint_id in context"}

        try:
            restored = self._rollback_engine.rollback_to(checkpoint_id)
            # Also isolate the failed branch if we have a node_id
            action = context.get("action", {})
            node_id = action.get("node_id", action.get("subtask_id", ""))
            if node_id and "current_state" in context:
                state_tree = context["current_state"].get("state_tree", {})
                if state_tree:
                    self._rollback_engine.isolate_failed_branch(node_id, state_tree)

            return {
                "success": True,
                "action": "rollback",
                "restored_state": restored,
                "instruction": "State restored — re-plan from checkpoint node",
            }
        except KeyError as exc:
            return {"success": False, "error": str(exc)}

    def _execute_branch(self, context: dict[str, Any]) -> dict[str, Any]:
        """Create an alternative branch from a checkpoint."""
        from_checkpoint = context.get("from_checkpoint", "")
        if not from_checkpoint:
            # Fall back to latest
            latest = self._checkpoint_mgr.get_latest()
            if latest is None:
                return {"success": False, "error": "No checkpoints for branching"}
            from_checkpoint = str(latest.checkpoint_id)

        new_subtask = {
            "objective": f"Alternative approach after failure: {context.get('error', 'unknown')}",
            "original_action": context.get("action", {}),
            "retry_count": context.get("retry_count", 0),
        }

        try:
            branch = self._rollback_engine.create_alternative_branch(
                from_checkpoint, new_subtask,
            )
            return {
                "success": True,
                "action": "branch",
                "branch": branch,
                "instruction": "Alternative branch created — try a different approach",
            }
        except KeyError as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _execute_escalate(context: dict[str, Any]) -> dict[str, Any]:
        """Prepare escalation to a human operator."""
        return {
            "success": True,
            "action": "escalate",
            "instruction": "Human intervention required",
            "failure_summary": {
                "error": context.get("error", ""),
                "retry_count": context.get("retry_count", 0),
                "action": context.get("action", {}),
                "consistency_issue": context.get("consistency_issue"),
            },
        }

    @staticmethod
    def _execute_abort(context: dict[str, Any]) -> dict[str, Any]:
        """Abort the current task."""
        return {
            "success": True,  # The abort itself succeeded
            "action": "abort",
            "instruction": "Task aborted — no further actions should be taken",
            "abort_reason": context.get("strategy_reason", "Unrecoverable failure"),
        }

    # -- statistics --------------------------------------------------------

    def get_recovery_stats(self) -> dict[str, Any]:
        """Return recovery metrics and summary statistics.

        Returns:
            Dict with failure counts, success rates, and recent recovery log.
        """
        return {
            "total_failures": self._total_failures,
            "successful_recoveries": self._successful_recoveries,
            "failed_recoveries": self._failed_recoveries,
            "recovery_rate": self.recovery_rate,
            "retry_counts": dict(self._retry_counts),
            "recent_recoveries": self._recovery_log[-10:],
        }

    # -- private helpers ---------------------------------------------------

    def _log_recovery(
        self,
        strategy: RecoveryStrategy,
        context: dict[str, Any],
        *,
        decided: bool,
    ) -> None:
        """Append an entry to the recovery audit log."""
        entry = {
            "strategy": strategy.name,
            "phase": "decision" if decided else "execution",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": {
                k: v for k, v in context.items()
                if k not in ("current_state",)  # avoid huge state dumps
            },
        }
        self._recovery_log.append(entry)
        logger.debug("Recovery log: %s", entry)
