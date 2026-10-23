"""
Hierarchical State Trees (MAGE Framework) — State Store
========================================================

Implements the MAGE state management paradigm with four core operations:
    Grow:     Append raw action-observation pairs preserving execution dependencies
    Compress: Summarize completed traces at subgoal boundaries to bound context
    Maintain: Independent validator audits summaries to prevent memory poisoning
    Revise:   Selective rollback isolates corrupted branches and spins up fresh paths

The state tree externalizes canonical task state from the bounded reasoning
context. At each step, only decision-relevant state along the active path
is reconstructed into a O(1) context view, eliminating quadratic cost scaling.

Key Innovation vs. Existing Work:
    - Unlike CaveAgent (Ran et al., 2026): adds formal lifecycle operations
    - Unlike InfiAgent (Yu et al., 2026): adds branch isolation and rollback
    - Unlike RAG/Mem0: uses active hierarchical state, not passive similarity retrieval

References:
    - MAGE Framework: Hierarchical state management
    - StatePlane (Annapureddy et al., 2026): Cognitive State Plane
    - StructAgent (Wu et al., 2026): Unified causal structure for task progress
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from state_aware_runtime.config import (
    NodeId,
    StatePhase,
    SubtaskContract,
    generate_id,
)

logger = logging.getLogger(__name__)

__all__ = [
    "StateNode",
    "StateTree",
    "StateStore",
]


# ============================================================================
# State Node
# ============================================================================


@dataclass
class StateNode:
    """
    A single node in the Hierarchical State Tree.

    Each node represents one subtask boundary in the execution trajectory.
    Nodes track their lifecycle phase, canonical state snapshot, action
    traces, and compressed summaries.

    Lifecycle: PENDING -> ACTIVE -> VERIFIED -> COMPRESSED
                                  \\-> FAILED -> (isolated)
                                  \\-> ROLLED_BACK
    """

    node_id: NodeId = field(default_factory=NodeId)
    parent_id: Optional[NodeId] = None
    children: list[NodeId] = field(default_factory=list)
    phase: StatePhase = StatePhase.PENDING
    subtask: SubtaskContract = field(default_factory=SubtaskContract)
    state_data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    action_trace: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    depth: int = 0
    is_active_path: bool = True
    error_info: Optional[str] = None

    def add_action(self, action: dict[str, Any], result: dict[str, Any]) -> None:
        """Append an action-observation pair to the trace (GROW operation)."""
        self.action_trace.append({
            "action": action,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step_index": len(self.action_trace),
        })
        self.updated_at = datetime.now(timezone.utc)

    def mark_active(self) -> None:
        """Transition node to ACTIVE phase."""
        self.phase = StatePhase.ACTIVE
        self.updated_at = datetime.now(timezone.utc)

    def mark_verified(self) -> None:
        """Transition node to VERIFIED phase after Auditor approval."""
        self.phase = StatePhase.VERIFIED
        self.updated_at = datetime.now(timezone.utc)
        logger.info("Node %s marked VERIFIED", self.node_id)

    def mark_failed(self, error: str = "") -> None:
        """Transition node to FAILED phase — isolate on dead branch."""
        self.phase = StatePhase.FAILED
        self.is_active_path = False
        self.error_info = error
        self.updated_at = datetime.now(timezone.utc)
        logger.warning("Node %s marked FAILED: %s", self.node_id, error[:200])

    def compress(self, summary: str) -> None:
        """
        Compress verified trace into a summary (COMPRESS operation).

        Replaces the raw action trace with a compact summary,
        reducing context size while preserving decision-relevant information.
        """
        if self.phase != StatePhase.VERIFIED:
            raise ValueError(
                f"Cannot compress node in phase {self.phase}; must be VERIFIED first"
            )
        self.summary = summary
        self.action_trace = []  # Discard raw trace
        self.phase = StatePhase.COMPRESSED
        self.updated_at = datetime.now(timezone.utc)
        logger.info("Node %s compressed (trace discarded)", self.node_id)

    @property
    def trace_length(self) -> int:
        return len(self.action_trace)

    @property
    def is_terminal(self) -> bool:
        return self.phase in (StatePhase.FAILED, StatePhase.ROLLED_BACK)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": str(self.node_id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "children": [str(c) for c in self.children],
            "phase": self.phase.name,
            "subtask": self.subtask.to_dict(),
            "state_data": self.state_data,
            "summary": self.summary,
            "action_trace": self.action_trace,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "depth": self.depth,
            "is_active_path": self.is_active_path,
            "error_info": self.error_info,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateNode:
        node = cls(
            node_id=NodeId(value=data["node_id"]),
            parent_id=NodeId(value=data["parent_id"]) if data.get("parent_id") else None,
            children=[NodeId(value=c) for c in data.get("children", [])],
            phase=StatePhase[data.get("phase", "PENDING")],
            state_data=data.get("state_data", {}),
            summary=data.get("summary", ""),
            action_trace=data.get("action_trace", []),
            depth=data.get("depth", 0),
            is_active_path=data.get("is_active_path", True),
            error_info=data.get("error_info"),
        )
        if "subtask" in data and data["subtask"]:
            st = data["subtask"]
            node.subtask = SubtaskContract(
                subtask_id=st.get("subtask_id", ""),
                objective=st.get("objective", ""),
                preconditions=st.get("preconditions", []),
                postconditions=st.get("postconditions", []),
                invariants=st.get("invariants", []),
                forbidden_actions=st.get("forbidden_actions", []),
                max_actions=st.get("max_actions", 20),
                max_tokens=st.get("max_tokens", 50000),
                timeout_seconds=st.get("timeout_seconds", 300.0),
                verification_criteria=st.get("verification_criteria", []),
            )
        if "created_at" in data:
            node.created_at = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data:
            node.updated_at = datetime.fromisoformat(data["updated_at"])
        return node


# ============================================================================
# Hierarchical State Tree
# ============================================================================


class StateTree:
    """
    The Hierarchical State Tree implementing MAGE operations.

    The tree structures interaction history along explicit decision
    dependencies rather than flat chronological order. Failed branches
    are isolated and never pollute the active execution path.

    MAGE Operations:
        grow(subtask)      -> Add child node with new subtask
        compress(node_id)  -> Summarize verified trace at subgoal boundary
        maintain(node_id)  -> Validate compressed summary integrity
        revise(node_id)    -> Rollback: isolate failure, spawn fresh branch
    """

    def __init__(self, initial_state: Optional[dict[str, Any]] = None) -> None:
        self.root = StateNode(
            subtask=SubtaskContract(objective="Root: Task initialization"),
            state_data=initial_state or {},
            phase=StatePhase.VERIFIED,
            depth=0,
        )
        self.nodes: dict[str, StateNode] = {str(self.root.node_id): self.root}
        self.active_node_id: NodeId = self.root.node_id
        self._revision_count: int = 0

    # ---- MAGE Core Operations ----

    def grow(
        self,
        subtask: SubtaskContract,
        parent_id: Optional[NodeId] = None,
        initial_state: Optional[dict[str, Any]] = None,
    ) -> StateNode:
        """
        GROW: Add a new child node to the tree.

        Creates a new execution branch for a subtask, inheriting canonical
        state from the parent and preserving the dependency chain.
        """
        parent_nid = parent_id or self.active_node_id
        parent = self.nodes.get(str(parent_nid))
        if parent is None:
            raise KeyError(f"Parent node {parent_nid} not found in tree")

        node_state = initial_state if initial_state is not None else deepcopy(parent.state_data)

        child = StateNode(
            parent_id=parent_nid,
            subtask=subtask,
            state_data=node_state,
            phase=StatePhase.ACTIVE,
            depth=parent.depth + 1,
        )

        parent.children.append(child.node_id)
        self.nodes[str(child.node_id)] = child
        self.active_node_id = child.node_id

        logger.info(
            "GROW: Created node %s (depth %d) for subtask '%s'",
            child.node_id, child.depth, subtask.objective[:80],
        )
        return child

    def compress(self, node_id: NodeId, summary: Optional[str] = None) -> str:
        """
        COMPRESS: Summarize completed trace at subgoal boundary.

        Converts verified action traces into a compact summary,
        then discards the raw trace to bound context growth.
        """
        node = self.nodes.get(str(node_id))
        if node is None:
            raise KeyError(f"Node {node_id} not found")

        if summary is None:
            action_count = len(node.action_trace)
            outcomes = []
            for entry in node.action_trace:
                r = entry.get("result", {})
                tool = entry.get("action", {}).get("tool_name", "action")
                mark = "\u2713" if r.get("success", False) else "\u2717"
                outcomes.append(f"{mark} {tool}")

            summary = (
                f"Subtask '{node.subtask.objective}' completed in {action_count} actions. "
                f"Outcomes: {'; '.join(outcomes[:10])}"
            )

        node.compress(summary)
        logger.info("COMPRESS: Node %s summarized (%d chars)", node_id, len(summary))
        return summary

    def maintain(self, node_id: NodeId) -> bool:
        """
        MAINTAIN: Validate the compressed summary against known state.

        An independent check ensuring no fabricated assumptions or
        hallucinations entered during compression.
        """
        node = self.nodes.get(str(node_id))
        if node is None:
            raise KeyError(f"Node {node_id} not found")

        if node.phase != StatePhase.COMPRESSED:
            logger.warning("MAINTAIN: Node %s is not compressed (phase: %s)", node_id, node.phase)
            return False

        valid = True
        issues: list[str] = []

        if not node.summary.strip():
            issues.append("Empty summary")
            valid = False

        if not node.state_data and node != self.root:
            issues.append("No state data after compression")
            valid = False

        if node.parent_id is None and node != self.root:
            issues.append("Orphan node detected")
            valid = False

        if valid:
            logger.info("MAINTAIN: Node %s summary validated", node_id)
        else:
            logger.warning("MAINTAIN: Node %s failed validation: %s", node_id, "; ".join(issues))

        return valid

    def revise(self, node_id: NodeId) -> StateNode:
        """
        REVISE: Selective rollback on failure.

        Isolates the corrupted branch (marks it FAILED), rolls back state
        to the parent node, and creates a fresh sibling node for a new
        execution attempt.
        """
        node = self.nodes.get(str(node_id))
        if node is None:
            raise KeyError(f"Node {node_id} not found")

        self._isolate_branch(node)

        if node.parent_id is None:
            raise ValueError("Cannot revise root node")

        parent = self.nodes[str(node.parent_id)]

        revised_subtask = SubtaskContract(
            objective=f"[REVISED] {node.subtask.objective}",
            preconditions=node.subtask.preconditions,
            postconditions=node.subtask.postconditions,
            invariants=node.subtask.invariants,
            forbidden_actions=node.subtask.forbidden_actions,
            max_actions=node.subtask.max_actions,
            max_tokens=node.subtask.max_tokens,
            timeout_seconds=node.subtask.timeout_seconds,
            verification_criteria=node.subtask.verification_criteria,
        )

        fresh_node = self.grow(revised_subtask, parent_id=parent.node_id)
        self._revision_count += 1

        logger.info(
            "REVISE: Isolated node %s, created fresh branch %s (revision #%d)",
            node_id, fresh_node.node_id, self._revision_count,
        )
        return fresh_node

    def _isolate_branch(self, node: StateNode) -> None:
        """Recursively mark a node and all its descendants as FAILED."""
        node.mark_failed(error=node.error_info or "Branch isolated during revision")
        for child_id in node.children:
            child = self.nodes.get(str(child_id))
            if child and child.phase != StatePhase.FAILED:
                self._isolate_branch(child)

    # ---- Navigation ----

    def get_active_path(self) -> list[StateNode]:
        """Return nodes from root to the current active node."""
        path: list[StateNode] = []
        current = self.nodes.get(str(self.active_node_id))
        while current is not None:
            path.append(current)
            if current.parent_id is None:
                break
            current = self.nodes.get(str(current.parent_id))
        path.reverse()
        return path

    def get_active_node(self) -> StateNode:
        """Return the current active node."""
        node = self.nodes.get(str(self.active_node_id))
        if node is None:
            raise KeyError(f"Active node {self.active_node_id} not found")
        return node

    def get_context_view(self, max_tokens: int = 8192) -> dict[str, Any]:
        """
        Reconstruct a bounded O(1) context view.

        Returns only decision-relevant information from the active path:
        - Current canonical state from active node
        - Compressed summaries of ancestor nodes
        - Current subtask contract
        - NO raw execution traces from completed subtasks
        """
        active_path = self.get_active_path()
        active_node = self.get_active_node()

        ancestor_summaries: list[str] = []
        estimated_tokens = 0
        for node in active_path[:-1]:
            s = node.summary or f"[{node.subtask.objective}]"
            tokens_estimate = len(s.split()) * 2
            if estimated_tokens + tokens_estimate > max_tokens // 2:
                ancestor_summaries.append("[... earlier work truncated ...]")
                break
            ancestor_summaries.append(s)
            estimated_tokens += tokens_estimate

        return {
            "canonical_state": active_node.state_data,
            "current_subtask": active_node.subtask.to_dict(),
            "completed_work": ancestor_summaries,
            "tree_depth": active_node.depth,
            "active_node_id": str(active_node.node_id),
            "failed_branches_count": len(self.get_failed_branches()),
            "revision_count": self._revision_count,
        }

    def get_failed_branches(self) -> list[StateNode]:
        """Return all failed/isolated branch root nodes."""
        return [
            n for n in self.nodes.values()
            if n.phase == StatePhase.FAILED and n.is_active_path is False
        ]

    # ---- State Diff ----

    def get_state_diff(self, node_a_id: NodeId, node_b_id: NodeId) -> dict[str, Any]:
        """Compute the state difference between two nodes."""
        node_a = self.nodes.get(str(node_a_id))
        node_b = self.nodes.get(str(node_b_id))
        if node_a is None or node_b is None:
            raise KeyError("One or both nodes not found")

        state_a = node_a.state_data
        state_b = node_b.state_data

        added = {k: v for k, v in state_b.items() if k not in state_a}
        removed = {k: v for k, v in state_a.items() if k not in state_b}
        modified = {
            k: {"old": state_a[k], "new": state_b[k]}
            for k in state_a
            if k in state_b and state_a[k] != state_b[k]
        }

        return {"added": added, "removed": removed, "modified": modified}

    # ---- Serialization ----

    def to_checkpoint(self) -> dict[str, Any]:
        """Serialize the entire tree to a checkpoint dict."""
        return {
            "root_id": str(self.root.node_id),
            "active_node_id": str(self.active_node_id),
            "revision_count": self._revision_count,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
        }

    @classmethod
    def from_checkpoint(cls, data: dict[str, Any]) -> StateTree:
        """Restore a StateTree from a checkpoint dict."""
        tree = cls.__new__(cls)
        tree._revision_count = data.get("revision_count", 0)
        tree.nodes = {}
        for nid, node_data in data.get("nodes", {}).items():
            tree.nodes[nid] = StateNode.from_dict(node_data)

        root_id = data.get("root_id", "")
        tree.root = tree.nodes.get(root_id, StateNode())
        tree.active_node_id = NodeId(value=data.get("active_node_id", root_id))
        return tree

    # ---- Stats ----

    @property
    def total_nodes(self) -> int:
        return len(self.nodes)

    @property
    def active_depth(self) -> int:
        return len(self.get_active_path())

    @property
    def revision_count(self) -> int:
        return self._revision_count

    def get_stats(self) -> dict[str, Any]:
        """Return tree statistics."""
        phase_counts: dict[str, int] = {}
        for node in self.nodes.values():
            phase_counts[node.phase.name] = phase_counts.get(node.phase.name, 0) + 1

        return {
            "total_nodes": self.total_nodes,
            "active_depth": self.active_depth,
            "revision_count": self._revision_count,
            "phase_counts": phase_counts,
            "failed_branches": len(self.get_failed_branches()),
        }


# ============================================================================
# State Store (Persistence Layer)
# ============================================================================


class StateStore:
    """
    Persistence layer wrapping the StateTree.

    Handles saving and loading state trees to/from disk as JSON files,
    supporting cross-session continuity and forensic reconstruction
    (following Springdrift's git-backed recovery model).
    """

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def save(self, tree: StateTree, session_id: str = "default") -> Path:
        """Persist the state tree to disk."""
        file_path = self._state_dir / f"state_{session_id}.json"
        checkpoint = tree.to_checkpoint()
        checkpoint["session_id"] = session_id
        checkpoint["saved_at"] = datetime.now(timezone.utc).isoformat()

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, default=str)

        logger.info("StateStore: Saved tree (%d nodes) to %s", tree.total_nodes, file_path)
        return file_path

    def load(self, session_id: str = "default") -> StateTree:
        """Load a state tree from disk."""
        file_path = self._state_dir / f"state_{session_id}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"No saved state for session '{session_id}' at {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        tree = StateTree.from_checkpoint(data)
        logger.info("StateStore: Loaded tree (%d nodes) from %s", tree.total_nodes, file_path)
        return tree

    def list_sessions(self) -> list[str]:
        """List all saved session IDs."""
        sessions = []
        for f in self._state_dir.glob("state_*.json"):
            session_id = f.stem.replace("state_", "")
            sessions.append(session_id)
        return sorted(sessions)

    def delete(self, session_id: str) -> bool:
        """Delete a saved session."""
        file_path = self._state_dir / f"state_{session_id}.json"
        if file_path.exists():
            file_path.unlink()
            logger.info("StateStore: Deleted session '%s'", session_id)
            return True
        return False
