"""
Configuration & Shared Types for State-Aware Durable Runtime.

Defines all enums, dataclasses, and policy objects shared across components.
This module serves as the type-theoretic foundation ensuring all components
speak a common language.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional


# ============================================================================
# Core Enums
# ============================================================================


class ActionVerdict(Enum):
    """Result of a behavioral contract evaluation on a proposed action."""
    APPROVE = auto()      # Action passes all gates
    REWRITE = auto()      # Action needs modification before execution
    BLOCK = auto()        # Action violates hard constraints — blocked
    ROLLBACK = auto()     # Action triggered a rollback condition


class StatePhase(Enum):
    """Lifecycle phase of a state node in the Hierarchical State Tree."""
    PENDING = auto()      # Proposed but not yet executed
    ACTIVE = auto()       # Currently being executed
    VERIFIED = auto()     # Execution completed and auditor-verified
    COMPRESSED = auto()   # Verified and summarized to save context
    FAILED = auto()       # Execution failed — isolated on dead branch
    ROLLED_BACK = auto()  # State rolled back to previous checkpoint


class MemoryTier(Enum):
    """Classification of memory entries by volatility and importance."""
    EPISODIC = auto()     # Short-term action-observation pairs (high decay)
    SEMANTIC = auto()     # Extracted facts and knowledge (medium decay)
    PROCEDURAL = auto()   # Learned procedures and patterns (low decay)
    CANONICAL = auto()    # Verified ground truth — never auto-decayed


class MemoryVerdict(Enum):
    """Result of write-path validation on a proposed memory entry."""
    ACCEPT = auto()       # Memory entry passes anti-poisoning checks
    QUARANTINE = auto()   # Suspicious — held for manual review
    REJECT = auto()       # Detected fabrication or poisoning — blocked


class CompletionVerdict(Enum):
    """Result of anti-fabrication firewall evaluation."""
    GENUINE = auto()      # Completion claim verified against environment
    FABRICATED = auto()   # Completion claim contradicts environment state
    INCOMPLETE = auto()   # Partial progress — not yet complete
    UNVERIFIABLE = auto() # Cannot verify — insufficient evidence


class RecoveryStrategy(Enum):
    """Strategy for recovering from detected failures."""
    RETRY = auto()        # Retry the failed action with same state
    ROLLBACK = auto()     # Roll back to last verified checkpoint
    BRANCH = auto()       # Create alternative branch and try different approach
    ESCALATE = auto()     # Escalate to human operator
    ABORT = auto()        # Abort the entire task


class DriftSeverity(Enum):
    """Severity classification of behavioral drift."""
    NONE = auto()         # No drift detected (D* < 0.10)
    LOW = auto()          # Minor drift within acceptable bounds (0.10 <= D* < 0.20)
    MODERATE = auto()     # Approaching drift boundary (0.20 <= D* < 0.27)
    HIGH = auto()         # Exceeds safe drift bound (D* >= 0.27)
    CRITICAL = auto()     # Severe drift requiring immediate intervention


# ============================================================================
# Identity Types
# ============================================================================


def generate_id(prefix: str = "sadr") -> str:
    """Generate a unique identifier with a given prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class SessionId:
    """Unique identifier for a runtime session."""
    value: str = field(default_factory=lambda: generate_id("sess"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CheckpointId:
    """Unique identifier for a state checkpoint."""
    value: str = field(default_factory=lambda: generate_id("ckpt"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class NodeId:
    """Unique identifier for a state tree node."""
    value: str = field(default_factory=lambda: generate_id("node"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ContractId:
    """Unique identifier for a behavioral contract."""
    value: str = field(default_factory=lambda: generate_id("cont"))

    def __str__(self) -> str:
        return self.value


# ============================================================================
# Action & Observation Types
# ============================================================================


@dataclass
class ActionProposal:
    """
    A proposed action from the LLM proposer.

    The LLM operates inside an ephemeral sandbox and proposes actions,
    but lacks authorization to write directly to persistent canonical state.
    Each proposal must pass through the Governance & Contract Layer.
    """
    action_id: str = field(default_factory=lambda: generate_id("act"))
    action_type: str = ""                     # e.g., "tool_call", "file_write", "shell_exec"
    tool_name: str = ""                       # Name of the tool to invoke
    parameters: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""                       # LLM's reasoning for this action
    proposed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    estimated_cost: float = 0.0               # Estimated token/compute cost
    subtask_id: str = ""                      # Which subtask this belongs to

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "rationale": self.rationale,
            "proposed_at": self.proposed_at.isoformat(),
            "estimated_cost": self.estimated_cost,
            "subtask_id": self.subtask_id,
        }


@dataclass
class ActionResult:
    """
    The result of executing an approved action.

    Contains both the raw output and structured state changes
    for the post-action auditor to verify.
    """
    action_id: str = ""
    success: bool = False
    output: str = ""                          # Raw execution output
    error: str | None = None                  # Error message if failed
    state_diff: dict[str, Any] = field(default_factory=dict)  # Changes to environment
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    execution_time_ms: float = 0.0
    tokens_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "success": self.success,
            "output": self.output[:500] if self.output else "",
            "error": self.error,
            "state_diff": self.state_diff,
            "executed_at": self.executed_at.isoformat(),
            "execution_time_ms": self.execution_time_ms,
            "tokens_used": self.tokens_used,
        }


@dataclass
class SubtaskContract:
    """
    A highly constrained subtask specification issued by the Manager.

    Defines what the Executor should accomplish, the boundaries of
    acceptable behavior, and the verification criteria for the Auditor.
    """
    subtask_id: str = field(default_factory=lambda: generate_id("sub"))
    objective: str = ""                       # What to accomplish
    preconditions: list[str] = field(default_factory=list)   # Must be true before starting
    postconditions: list[str] = field(default_factory=list)  # Must be true after completion
    invariants: list[str] = field(default_factory=list)      # Must remain true throughout
    forbidden_actions: list[str] = field(default_factory=list)  # Never allowed
    max_actions: int = 20                     # Action budget for this subtask
    max_tokens: int = 50000                   # Token budget for this subtask
    timeout_seconds: float = 300.0            # Time budget
    verification_criteria: list[str] = field(default_factory=list)  # How auditor checks

    def to_dict(self) -> dict[str, Any]:
        return {
            "subtask_id": self.subtask_id,
            "objective": self.objective,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "invariants": self.invariants,
            "forbidden_actions": self.forbidden_actions,
            "max_actions": self.max_actions,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "verification_criteria": self.verification_criteria,
        }


# ============================================================================
# Policy Configurations
# ============================================================================


@dataclass
class ContractPolicy:
    """
    Policy for runtime behavioral contract enforcement.

    Based on Agent Behavioral Contracts (Bhardwaj, 2026) achieving
    88-100% hard-constraint compliance with bounded drift D* < 0.27.
    """
    max_drift_score: float = 0.27             # Maximum allowable drift (D* threshold)
    hard_constraint_mode: str = "block"       # "block" | "rewrite" | "warn"
    soft_constraint_mode: str = "warn"        # "block" | "rewrite" | "warn"
    enable_pre_action_gate: bool = True
    enable_action_monitor: bool = True
    enable_post_action_audit: bool = True
    max_contract_violations: int = 3          # Max violations before escalation
    drift_window_size: int = 10               # Actions to consider for drift calculation


@dataclass
class MemoryPolicy:
    """
    Policy for memory lifecycle governance.

    Based on SSGM Framework (Lam et al., 2026) and ACC
    (Bousetouane, 2026) for anti-poisoning and selective decay.
    """
    enable_write_validation: bool = True      # Anti-poisoning on memory writes
    enable_decay: bool = True                 # Selective forgetting
    episodic_decay_rate: float = 0.15         # Per-step decay for episodic memory
    semantic_decay_rate: float = 0.02         # Per-step decay for semantic memory
    procedural_decay_rate: float = 0.005      # Per-step decay for procedural memory
    min_confidence_threshold: float = 0.3     # Below this, memory is garbage-collected
    max_episodic_entries: int = 100           # Cap on episodic memory
    max_semantic_entries: int = 500           # Cap on semantic memory
    poisoning_similarity_threshold: float = 0.85  # Threshold for contradiction detection
    quarantine_on_conflict: bool = True       # Quarantine conflicting memories


@dataclass
class RecoveryPolicy:
    """
    Policy for checkpoint/restore and rollback.

    Based on Crab (Wu et al., 2026) for semantics-aware checkpointing
    and Rewind-IL (Zheng et al., 2026) for self-consistency monitoring.
    """
    enable_auto_checkpoint: bool = True       # Auto-checkpoint at subgoal boundaries
    checkpoint_interval_actions: int = 5      # Checkpoint every N actions
    max_checkpoints: int = 50                 # Maximum stored checkpoints
    enable_branch_isolation: bool = True      # Isolate failed branches
    max_retry_attempts: int = 3               # Max retries before escalation
    rollback_on_drift_threshold: float = 0.27 # Auto-rollback if drift exceeds this
    enable_speculative_execution: bool = False # DSE-style speculative execution


@dataclass
class FirewallPolicy:
    """
    Policy for anti-fabrication firewall.

    Based on Goal-Autopilot (Deng, 2026) making false completion
    structurally impossible via environment verification.
    """
    require_environment_verification: bool = True    # Must verify against env
    require_artifact_evidence: bool = True           # Must show concrete artifacts
    min_verification_checks: int = 2                 # Minimum independent checks
    block_unverifiable_claims: bool = True            # Block if can't verify
    enable_hash_verification: bool = True            # MD5/SHA verification of outputs


@dataclass
class RuntimeConfig:
    """
    Master configuration for the State-Aware Durable Runtime.

    Aggregates all component policies into a single configuration
    object with sensible defaults based on published research results.
    """
    # Session
    session_id: SessionId = field(default_factory=SessionId)
    workspace_dir: Path = field(default_factory=lambda: Path("./workspace"))
    state_dir: Path = field(default_factory=lambda: Path("./state"))
    log_dir: Path = field(default_factory=lambda: Path("./logs"))

    # Component policies
    contract_policy: ContractPolicy = field(default_factory=ContractPolicy)
    memory_policy: MemoryPolicy = field(default_factory=MemoryPolicy)
    recovery_policy: RecoveryPolicy = field(default_factory=RecoveryPolicy)
    firewall_policy: FirewallPolicy = field(default_factory=FirewallPolicy)

    # Global budgets
    max_total_actions: int = 500              # Hard action limit per session
    max_total_tokens: int = 2_000_000         # Hard token limit per session
    max_session_duration_seconds: float = 7200.0  # 2-hour session limit

    # Context management
    max_context_tokens: int = 8192            # Bounded reasoning window (O(1))
    context_reconstruction_mode: str = "relevant"  # "relevant" | "recent" | "full"

    # Logging
    enable_lineage_logging: bool = True
    lineage_format: str = "jsonl"             # "jsonl" | "json"
    log_level: str = "INFO"

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
