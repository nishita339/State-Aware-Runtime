"""
Runtime Behavioral Contracts — Pre-Action Gate / Action-Time Monitor / Post-Action Auditor.

Implements the three-stage contract enforcement pipeline from:
  - Agent Behavioral Contracts (Bhardwaj, 2026) achieving 88–100% hard-constraint
    compliance with bounded drift D* < 0.27.
  - SARC (Besanson, 2026) Pre-Action Gate / Action-Time Monitor / Post-Action Auditor
    architecture for continuous governance of autonomous agents.

The core idea: every action proposed by the LLM Proposer must survive three
sequential gates before its results are committed to canonical state.

  ┌──────────────┐    ┌───────────────┐    ┌─────────────────┐
  │ PreActionGate │──▶ │ ActionMonitor │──▶ │ PostActionAudit │
  └──────────────┘    └───────────────┘    └─────────────────┘
       (before)           (during)              (after)

Drift D* is computed over a sliding window of recent actions as the
mean penalty-weighted violation rate.  When D* ≥ 0.27 the system
escalates — either blocking further actions or triggering rollback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from state_aware_runtime.config import (
    ActionProposal,
    ActionResult,
    ActionVerdict,
    ContractId,
    ContractPolicy,
    DriftSeverity,
    generate_id,
)

__all__ = [
    "ContractClause",
    "BehavioralContract",
    "DriftMonitor",
    "PreActionGate",
    "ActionMonitor",
    "PostActionAudit",
    "ContractEngine",
]

logger = logging.getLogger(__name__)


# ============================================================================
# ContractClause
# ============================================================================


@dataclass
class ContractClause:
    """A single enforceable clause within a behavioral contract.

    Each clause encapsulates one verifiable constraint.  Clauses are
    categorised by *clause_type* and *severity*:

    clause_type:
        - ``"precondition"``  — must hold *before* an action starts.
        - ``"postcondition"`` — must hold *after* an action completes.
        - ``"invariant"``     — must hold *throughout* execution.
        - ``"forbidden"``     — defines an action pattern that is never allowed.
        - ``"recovery"``      — specifies a recovery path on violation.

    severity:
        - ``"hard"`` — violation is non-negotiable; the action is blocked.
        - ``"soft"`` — violation is undesirable; it contributes to drift
          but does not immediately block.

    The *penalty* field feeds into the drift metric D* (Bhardwaj, 2026).
    A higher penalty means the violation contributes more to the
    cumulative drift score.

    Attributes:
        clause_id:   Unique identifier for this clause.
        clause_type: One of the five categories listed above.
        description: Human-readable description used in audit logs.
        check_fn:    Callable that evaluates the clause against a state
                     dictionary, returning ``True`` when the clause is
                     *satisfied*.
        severity:    ``"hard"`` or ``"soft"``.
        penalty:     Drift penalty ∈ [0, 1] assessed on violation.
    """

    clause_id: str = field(default_factory=lambda: generate_id("clse"))
    clause_type: str = "invariant"
    description: str = ""
    check_fn: Callable[[dict[str, Any]], bool] = field(
        default_factory=lambda: (lambda _state: True)
    )
    severity: str = "hard"
    penalty: float = 0.1

    # -- helpers -------------------------------------------------------------

    def evaluate(self, state: dict[str, Any]) -> bool:
        """Run *check_fn* against *state* and return the boolean result.

        Catches exceptions from user-supplied *check_fn* and treats them
        as a violation (returns ``False``), logging the error.
        """
        try:
            return self.check_fn(state)
        except Exception:
            logger.exception(
                "Clause %s (%s) raised during evaluation",
                self.clause_id,
                self.description,
            )
            return False

    @property
    def is_hard(self) -> bool:
        """Return ``True`` when the clause is a hard constraint."""
        return self.severity == "hard"


# ============================================================================
# BehavioralContract
# ============================================================================


@dataclass
class BehavioralContract:
    """A collection of :class:`ContractClause` instances governing agent behaviour.

    Contracts are the *policy specification* layer described in Bhardwaj (2026).
    They declaratively enumerate what the agent may, must, and must-not do
    during a bounded execution episode.

    The contract provides convenience views that partition clauses by type:

    * :pyattr:`preconditions`
    * :pyattr:`postconditions`
    * :pyattr:`invariants`
    * :pyattr:`forbidden_actions`

    Attributes:
        contract_id: Typed identifier (see :class:`ContractId`).
        name:        Human-readable label for this contract.
        clauses:     Flat list of all clauses regardless of type.
    """

    contract_id: ContractId = field(default_factory=ContractId)
    name: str = ""
    clauses: list[ContractClause] = field(default_factory=list)

    # -- categorised views ---------------------------------------------------

    @property
    def preconditions(self) -> list[ContractClause]:
        """All clauses with ``clause_type == "precondition"``."""
        return [c for c in self.clauses if c.clause_type == "precondition"]

    @property
    def postconditions(self) -> list[ContractClause]:
        """All clauses with ``clause_type == "postcondition"``."""
        return [c for c in self.clauses if c.clause_type == "postcondition"]

    @property
    def invariants(self) -> list[ContractClause]:
        """All clauses with ``clause_type == "invariant"``."""
        return [c for c in self.clauses if c.clause_type == "invariant"]

    @property
    def forbidden_actions(self) -> list[ContractClause]:
        """All clauses with ``clause_type == "forbidden"``."""
        return [c for c in self.clauses if c.clause_type == "forbidden"]

    # -- mutation ------------------------------------------------------------

    def add_clause(self, clause: ContractClause) -> None:
        """Append *clause* to the contract.

        Raises :class:`ValueError` if a clause with the same
        ``clause_id`` already exists.
        """
        if any(c.clause_id == clause.clause_id for c in self.clauses):
            raise ValueError(
                f"Clause {clause.clause_id!r} already exists in contract "
                f"{self.contract_id}"
            )
        self.clauses.append(clause)
        logger.info(
            "Contract %s: added clause %s (%s)",
            self.contract_id,
            clause.clause_id,
            clause.clause_type,
        )

    def remove_clause(self, clause_id: str) -> None:
        """Remove the clause identified by *clause_id*.

        Raises :class:`KeyError` if no such clause exists.
        """
        for idx, clause in enumerate(self.clauses):
            if clause.clause_id == clause_id:
                self.clauses.pop(idx)
                logger.info(
                    "Contract %s: removed clause %s",
                    self.contract_id,
                    clause_id,
                )
                return
        raise KeyError(
            f"No clause with id {clause_id!r} in contract {self.contract_id}"
        )

    # -- evaluation helpers --------------------------------------------------

    def check_preconditions(
        self, state: dict[str, Any]
    ) -> list[tuple[ContractClause, bool]]:
        """Evaluate every precondition clause against *state*.

        Returns a list of ``(clause, passed)`` pairs.
        """
        return [(c, c.evaluate(state)) for c in self.preconditions]

    def check_postconditions(
        self, state: dict[str, Any]
    ) -> list[tuple[ContractClause, bool]]:
        """Evaluate every postcondition clause against *state*."""
        return [(c, c.evaluate(state)) for c in self.postconditions]

    def check_invariants(
        self, state: dict[str, Any]
    ) -> list[tuple[ContractClause, bool]]:
        """Evaluate every invariant clause against *state*."""
        return [(c, c.evaluate(state)) for c in self.invariants]

    def check_forbidden(
        self, action: ActionProposal
    ) -> list[tuple[ContractClause, bool]]:
        """Evaluate every forbidden clause against *action*.

        For forbidden clauses the ``check_fn`` receives the action's
        ``to_dict()`` representation.  A return value of ``True`` from
        ``check_fn`` means the action is *permissible* (the forbidden
        pattern was **not** matched).  ``False`` means the action
        matches the forbidden pattern and must be blocked.
        """
        action_state = action.to_dict()
        return [(c, c.evaluate(action_state)) for c in self.forbidden_actions]


# ============================================================================
# DriftMonitor
# ============================================================================


@dataclass
class DriftMonitor:
    """Tracks behavioural drift over a sliding window of recent actions.

    Drift D* (Bhardwaj, 2026) is the mean penalty-weighted violation rate
    computed over the last *window_size* actions.  The bound D* < 0.27
    was empirically validated to maintain 88–100% hard-constraint
    compliance across diverse benchmark environments.

    Attributes:
        drift_history: Per-action drift scores (penalty sums).
        window_size:   Number of recent actions in the sliding window.
        threshold:     D* upper bound (default 0.27).
    """

    drift_history: list[float] = field(default_factory=list)
    window_size: int = 10
    threshold: float = 0.27

    # -- recording -----------------------------------------------------------

    def record_action(
        self,
        action: ActionProposal,
        result: ActionResult,
        violations: list[ContractClause],
    ) -> None:
        """Record the drift contribution of a single executed action.

        The drift score for the action is the sum of *penalty* values
        across all violated clauses.  A clean action contributes 0.0.

        Args:
            action:     The proposed (and executed) action.
            result:     The execution result.
            violations: Clauses that were violated during or after
                        execution of *action*.
        """
        score = sum(v.penalty for v in violations)
        self.drift_history.append(score)
        logger.debug(
            "DriftMonitor: action %s drift=%.4f (violations=%d)",
            action.action_id,
            score,
            len(violations),
        )

    # -- queries -------------------------------------------------------------

    def current_drift(self) -> float:
        """Compute D* as the mean drift over the sliding window.

        Returns 0.0 when no actions have been recorded.
        """
        if not self.drift_history:
            return 0.0
        window = self.drift_history[-self.window_size :]
        return sum(window) / len(window)

    def severity(self) -> DriftSeverity:
        """Classify current drift into a :class:`DriftSeverity` level.

        The thresholds match those documented in the ``DriftSeverity``
        enum (config.py):
          - NONE:     D* < 0.10
          - LOW:      0.10 ≤ D* < 0.20
          - MODERATE: 0.20 ≤ D* < 0.27
          - HIGH:     0.27 ≤ D* < 0.50
          - CRITICAL: D* ≥ 0.50
        """
        d = self.current_drift()
        if d < 0.10:
            return DriftSeverity.NONE
        if d < 0.20:
            return DriftSeverity.LOW
        if d < 0.27:
            return DriftSeverity.MODERATE
        if d < 0.50:
            return DriftSeverity.HIGH
        return DriftSeverity.CRITICAL

    def is_within_bounds(self) -> bool:
        """Return ``True`` when D* < *threshold* (default 0.27)."""
        return self.current_drift() < self.threshold

    def get_drift_trend(self) -> str:
        """Classify the recent drift trajectory.

        Compares the mean of the first half of the window against the
        second half.  Returns one of:
          - ``"increasing"`` — drift is growing.
          - ``"decreasing"`` — drift is shrinking.
          - ``"stable"``     — drift is approximately flat (< 5% change).
        """
        if len(self.drift_history) < 2:
            return "stable"
        window = self.drift_history[-self.window_size :]
        mid = len(window) // 2
        first_half = window[:mid] or [0.0]
        second_half = window[mid:] or [0.0]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        diff = avg_second - avg_first
        if abs(diff) < 0.05:
            return "stable"
        return "increasing" if diff > 0 else "decreasing"


# ============================================================================
# PreActionGate
# ============================================================================


class PreActionGate:
    """Evaluates preconditions and forbidden-action rules *before* tool dispatch.

    This is the first stage of the SARC (Besanson, 2026) three-stage
    governance pipeline.  The gate inspects the :class:`ActionProposal`
    and the *current* environment state, then returns an
    :class:`ActionVerdict` with a list of human-readable reasons.

    Decision logic:
      1. Check forbidden clauses — any hard violation → BLOCK.
      2. Check preconditions   — any hard failure   → BLOCK.
      3. Soft violations are collected as reasons but yield REWRITE
         (the proposer may re-plan).
      4. All checks pass → APPROVE.
    """

    def evaluate(
        self,
        action: ActionProposal,
        current_state: dict[str, Any],
        contract: BehavioralContract,
    ) -> tuple[ActionVerdict, list[str]]:
        """Evaluate *action* against *contract* using *current_state*.

        Args:
            action:        The proposed action to vet.
            current_state: A snapshot of the current environment state.
            contract:      The governing :class:`BehavioralContract`.

        Returns:
            A ``(verdict, reasons)`` tuple.  *reasons* is a list of
            human-readable strings describing each violation found.
        """
        reasons: list[str] = []

        # --- Forbidden actions ---
        forbidden_results = contract.check_forbidden(action)
        for clause, passed in forbidden_results:
            if not passed:
                msg = (
                    f"[FORBIDDEN] {clause.description} "
                    f"(clause={clause.clause_id}, severity={clause.severity})"
                )
                reasons.append(msg)
                if clause.is_hard:
                    logger.warning(
                        "PreActionGate BLOCK: hard forbidden clause %s "
                        "violated by action %s",
                        clause.clause_id,
                        action.action_id,
                    )
                    return ActionVerdict.BLOCK, reasons

        # --- Preconditions ---
        precond_results = contract.check_preconditions(current_state)
        for clause, passed in precond_results:
            if not passed:
                msg = (
                    f"[PRECONDITION] {clause.description} "
                    f"(clause={clause.clause_id}, severity={clause.severity})"
                )
                reasons.append(msg)
                if clause.is_hard:
                    logger.warning(
                        "PreActionGate BLOCK: hard precondition %s "
                        "failed for action %s",
                        clause.clause_id,
                        action.action_id,
                    )
                    return ActionVerdict.BLOCK, reasons

        # --- Soft violations → REWRITE ---
        if reasons:
            logger.info(
                "PreActionGate REWRITE: %d soft violations for action %s",
                len(reasons),
                action.action_id,
            )
            return ActionVerdict.REWRITE, reasons

        # --- All clear ---
        logger.debug("PreActionGate APPROVE: action %s", action.action_id)
        return ActionVerdict.APPROVE, []


# ============================================================================
# ActionMonitor
# ============================================================================


class ActionMonitor:
    """Intercepts execution mid-flight to verify invariants still hold.

    Second stage of the SARC pipeline (Besanson, 2026).  While the tool
    executor is running, the monitor samples the environment state and
    checks all invariant clauses of the active contract.

    If any invariant fails the monitor reports the failure so the runtime
    can pause, rewrite, or abort the action.
    """

    def check_invariants(
        self,
        current_state: dict[str, Any],
        contract: BehavioralContract,
    ) -> tuple[bool, list[str]]:
        """Verify that all invariant clauses hold in *current_state*.

        Args:
            current_state: A snapshot of the environment taken during
                           action execution.
            contract:      The governing :class:`BehavioralContract`.

        Returns:
            A ``(all_pass, violation_descriptions)`` tuple.
            ``all_pass`` is ``True`` only when every invariant is satisfied.
        """
        violations: list[str] = []
        inv_results = contract.check_invariants(current_state)
        for clause, passed in inv_results:
            if not passed:
                msg = (
                    f"[INVARIANT] {clause.description} "
                    f"(clause={clause.clause_id}, severity={clause.severity})"
                )
                violations.append(msg)
                logger.warning(
                    "ActionMonitor: invariant %s violated", clause.clause_id
                )

        all_pass = len(violations) == 0
        if all_pass:
            logger.debug("ActionMonitor: all invariants hold")
        return all_pass, violations


# ============================================================================
# PostActionAudit
# ============================================================================


class PostActionAudit:
    """Validates the state-diff produced by an action after execution.

    Third and final stage of the SARC pipeline (Besanson, 2026).
    The auditor compares pre- and post-execution state snapshots against
    the contract's postconditions and invariants to determine whether
    the action's effects are acceptable.

    Decision logic:
      1. Evaluate postconditions against *post_state*.
      2. Re-evaluate invariants against *post_state* (they may have been
         broken by side-effects invisible to the mid-flight monitor).
      3. Any hard violation → ROLLBACK.
      4. Soft violations → REWRITE (allow but flag).
      5. All pass → APPROVE.
    """

    def evaluate(
        self,
        action: ActionProposal,
        result: ActionResult,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
        contract: BehavioralContract,
    ) -> tuple[ActionVerdict, list[str]]:
        """Audit the effects of *action* after execution.

        Args:
            action:     The action that was executed.
            result:     The execution result.
            pre_state:  State snapshot taken *before* execution.
            post_state: State snapshot taken *after* execution.
            contract:   The governing :class:`BehavioralContract`.

        Returns:
            A ``(verdict, reasons)`` tuple.
        """
        reasons: list[str] = []
        has_hard_violation = False

        # --- Postconditions ---
        post_results = contract.check_postconditions(post_state)
        for clause, passed in post_results:
            if not passed:
                msg = (
                    f"[POSTCONDITION] {clause.description} "
                    f"(clause={clause.clause_id}, severity={clause.severity})"
                )
                reasons.append(msg)
                if clause.is_hard:
                    has_hard_violation = True

        # --- Invariants (re-check after execution) ---
        inv_results = contract.check_invariants(post_state)
        for clause, passed in inv_results:
            if not passed:
                msg = (
                    f"[INVARIANT-POST] {clause.description} "
                    f"(clause={clause.clause_id}, severity={clause.severity})"
                )
                reasons.append(msg)
                if clause.is_hard:
                    has_hard_violation = True

        # --- Verdict ---
        if has_hard_violation:
            logger.warning(
                "PostActionAudit ROLLBACK: hard violation(s) for action %s",
                action.action_id,
            )
            return ActionVerdict.ROLLBACK, reasons

        if reasons:
            logger.info(
                "PostActionAudit REWRITE: %d soft violations for action %s",
                len(reasons),
                action.action_id,
            )
            return ActionVerdict.REWRITE, reasons

        logger.debug("PostActionAudit APPROVE: action %s", action.action_id)
        return ActionVerdict.APPROVE, []


# ============================================================================
# ContractEngine
# ============================================================================


class ContractEngine:
    """Orchestrates the full three-stage SARC governance pipeline.

    The engine wires together :class:`PreActionGate`,
    :class:`ActionMonitor`, :class:`PostActionAudit`, and
    :class:`DriftMonitor` under a single :class:`ContractPolicy`.

    Each registered :class:`BehavioralContract` is evaluated during every
    gate.  The engine maintains cumulative statistics (total, hard, and
    soft violations) and exposes a :meth:`compliance_rate` reflecting
    the fraction of clean actions.

    Typical lifecycle::

        engine = ContractEngine(policy)
        engine.register_contract(my_contract)

        verdict, reasons = engine.evaluate_proposal(action, state)
        if verdict == ActionVerdict.APPROVE:
            # execute the action …
            ok, inv_reasons = engine.monitor_execution(mid_state)
            audit_verdict, audit_reasons = engine.audit_result(
                action, result, pre_state, post_state
            )

    Args:
        policy: A :class:`ContractPolicy` controlling thresholds, modes,
                and enabled stages.

    References:
        Bhardwaj (2026).  Agent Behavioral Contracts.
        Besanson (2026).  SARC: State-Aware Runtime Contracts.
    """

    def __init__(self, policy: ContractPolicy) -> None:
        self._policy = policy
        self._contracts: list[BehavioralContract] = []
        self._gate = PreActionGate()
        self._monitor = ActionMonitor()
        self._auditor = PostActionAudit()
        self._drift = DriftMonitor(
            window_size=policy.drift_window_size,
            threshold=policy.max_drift_score,
        )

        # Cumulative counters
        self._total_evaluations: int = 0
        self._total_violations: int = 0
        self._hard_violations: int = 0
        self._soft_violations: int = 0

        logger.info(
            "ContractEngine initialised (drift_window=%d, max_drift=%.2f)",
            policy.drift_window_size,
            policy.max_drift_score,
        )

    # -- contract management -------------------------------------------------

    def register_contract(self, contract: BehavioralContract) -> None:
        """Register a :class:`BehavioralContract` for enforcement.

        Multiple contracts may be registered; all are evaluated at each
        gate.

        Raises:
            ValueError: If a contract with the same ``contract_id``
                        is already registered.
        """
        if any(
            c.contract_id == contract.contract_id for c in self._contracts
        ):
            raise ValueError(
                f"Contract {contract.contract_id} is already registered"
            )
        self._contracts.append(contract)
        logger.info(
            "ContractEngine: registered contract %s (%s) with %d clauses",
            contract.contract_id,
            contract.name,
            len(contract.clauses),
        )

    # -- three-stage pipeline ------------------------------------------------

    def evaluate_proposal(
        self,
        action: ActionProposal,
        state: dict[str, Any],
    ) -> tuple[ActionVerdict, list[str]]:
        """Stage 1 — Pre-Action Gate.

        Evaluates the proposed *action* against all registered contracts
        using the current *state*.  Returns the strictest verdict across
        contracts (BLOCK > REWRITE > APPROVE).
        """
        if not self._policy.enable_pre_action_gate:
            return ActionVerdict.APPROVE, []

        all_reasons: list[str] = []
        worst_verdict = ActionVerdict.APPROVE

        for contract in self._contracts:
            verdict, reasons = self._gate.evaluate(action, state, contract)
            all_reasons.extend(reasons)
            if verdict.value > worst_verdict.value:
                worst_verdict = verdict

        self._record_violations(all_reasons)
        return worst_verdict, all_reasons

    def monitor_execution(
        self, state: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Stage 2 — Action-Time Monitor.

        Checks invariants of all registered contracts against the
        in-flight *state* snapshot.
        """
        if not self._policy.enable_action_monitor:
            return True, []

        all_violations: list[str] = []
        for contract in self._contracts:
            ok, violations = self._monitor.check_invariants(state, contract)
            all_violations.extend(violations)

        if all_violations:
            self._record_violations(all_violations)

        return len(all_violations) == 0, all_violations

    def audit_result(
        self,
        action: ActionProposal,
        result: ActionResult,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
    ) -> tuple[ActionVerdict, list[str]]:
        """Stage 3 — Post-Action Audit.

        Validates the state-diff produced by *action* and updates the
        drift monitor.
        """
        if not self._policy.enable_post_action_audit:
            # Still record a clean action for drift tracking.
            self._drift.record_action(action, result, [])
            return ActionVerdict.APPROVE, []

        all_reasons: list[str] = []
        worst_verdict = ActionVerdict.APPROVE
        violated_clauses: list[ContractClause] = []

        for contract in self._contracts:
            verdict, reasons = self._auditor.evaluate(
                action, result, pre_state, post_state, contract
            )
            all_reasons.extend(reasons)
            if verdict.value > worst_verdict.value:
                worst_verdict = verdict

            # Collect violated clauses for drift recording.
            for clause in contract.clauses:
                if clause.clause_type in ("postcondition", "invariant"):
                    if not clause.evaluate(post_state):
                        violated_clauses.append(clause)

        self._drift.record_action(action, result, violated_clauses)
        self._record_violations(all_reasons)
        self._total_evaluations += 1

        return worst_verdict, all_reasons

    # -- drift status --------------------------------------------------------

    def get_drift_status(self) -> dict[str, Any]:
        """Return a dictionary summarising current drift metrics.

        Keys:
            - ``current_drift``: the computed D* value.
            - ``severity``:      human-readable severity label.
            - ``within_bounds``: ``True`` when D* < threshold.
            - ``trend``:         ``"increasing"`` / ``"stable"`` /
                                 ``"decreasing"``.
            - ``history_len``:   number of recorded actions.
            - ``threshold``:     the configured D* threshold.
        """
        return {
            "current_drift": self._drift.current_drift(),
            "severity": self._drift.severity().name,
            "within_bounds": self._drift.is_within_bounds(),
            "trend": self._drift.get_drift_trend(),
            "history_len": len(self._drift.drift_history),
            "threshold": self._drift.threshold,
        }

    # -- aggregate statistics ------------------------------------------------

    @property
    def total_violations(self) -> int:
        """Total number of violations (hard + soft) recorded."""
        return self._total_violations

    @property
    def hard_violations(self) -> int:
        """Number of hard-constraint violations recorded."""
        return self._hard_violations

    @property
    def soft_violations(self) -> int:
        """Number of soft-constraint violations recorded."""
        return self._soft_violations

    @property
    def compliance_rate(self) -> float:
        """Fraction of evaluations with zero violations ∈ [0, 1].

        Returns 1.0 when no evaluations have occurred yet.
        """
        if self._total_evaluations == 0:
            return 1.0
        clean = self._total_evaluations - min(
            self._total_violations, self._total_evaluations
        )
        return clean / self._total_evaluations

    # -- internals -----------------------------------------------------------

    def _record_violations(self, reasons: list[str]) -> None:
        """Update internal violation counters from a list of reason strings.

        Reasons are expected to be formatted by the gate/monitor/auditor
        classes with a ``severity=…`` tag.  Hard vs. soft classification
        is inferred from this tag.
        """
        for reason in reasons:
            self._total_violations += 1
            if "severity=hard" in reason:
                self._hard_violations += 1
            else:
                self._soft_violations += 1
