"""
Anti-Fabrication Firewall — Environment-Verified Completion Claims.

Implements the Goal-Autopilot (Deng, 2026) architecture that makes false
"done" claims **structurally impossible** by requiring every completion
claim to survive independent environment verification before it is
accepted by the runtime.

The core invariant:

    claim_accepted  ⟹  ∀ check ∈ registered_checks : check.passed

An agent may *assert* that a file was written, a test passed, or an API
returned 200 — but the firewall will independently inspect the filesystem,
run the command, or hash the artifact before the claim is committed.

Pipeline::

    Agent ──▶ CompletionClaim ──▶ AntiFabricationFirewall.verify_claim()
                                        │
                                        ├── EnvironmentCheck 1  ✓
                                        ├── EnvironmentCheck 2  ✓
                                        ├── EnvironmentCheck 3  ✗ → FABRICATED
                                        │
                                        └── VerificationResult
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from state_aware_runtime.config import (
    CompletionVerdict,
    FirewallPolicy,
    generate_id,
)

__all__ = [
    "CompletionClaim",
    "EnvironmentCheck",
    "VerificationResult",
    "AntiFabricationFirewall",
]

logger = logging.getLogger(__name__)


# ============================================================================
# CompletionClaim
# ============================================================================


@dataclass
class CompletionClaim:
    """An agent's assertion that a subtask has been completed.

    The claim is the *input* to the firewall — it describes what the
    agent believes it has accomplished together with the artifacts and
    evidence it can point to.

    The firewall treats the claim as *untrusted* until every registered
    :class:`EnvironmentCheck` confirms it (Goal-Autopilot, Deng 2026).

    Attributes:
        claim_id:           Unique identifier for this claim.
        subtask_id:         The subtask the agent claims to have finished.
        claimed_at:         Timestamp of the claim.
        claimed_artifacts:  File paths or output identifiers the agent
                            says it produced.
        claimed_evidence:   Free-form evidence dictionary supplied by the
                            agent (e.g. ``{"test_output": "PASSED"}``).
        agent_confidence:   The agent's self-reported confidence ∈ [0, 1].
    """

    claim_id: str = field(default_factory=lambda: generate_id("clm"))
    subtask_id: str = ""
    claimed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    claimed_artifacts: list[str] = field(default_factory=list)
    claimed_evidence: dict[str, Any] = field(default_factory=dict)
    agent_confidence: float = 1.0


# ============================================================================
# EnvironmentCheck
# ============================================================================


@dataclass
class EnvironmentCheck:
    """A single, independently verifiable check against the real environment.

    Each check encapsulates one observable predicate.  The ``check_fn``
    receives two arguments — the workspace :class:`Path` and a state
    dictionary — and must return ``True`` when the check passes.

    Supported ``check_type`` values (by convention):
      - ``"file_exists"``     — assert a file is present on disk.
      - ``"file_content"``    — assert file contents match expected patterns.
      - ``"hash_match"``      — assert SHA-256 hash of a file matches.
      - ``"command_output"``  — run a shell command and match its stdout.
      - ``"state_match"``     — compare a state-dict key against expected.

    Attributes:
        check_id:    Unique identifier for this check.
        check_type:  Category string (see above).
        description: Human-readable label used in audit logs.
        check_fn:    Callable ``(workspace: Path, state: dict) → bool``.
        expected:    The expected value or pattern (for logging / diffing).
        actual:      The actual observed value (populated after evaluation).
        passed:      Whether the check passed (populated after evaluation).
    """

    check_id: str = field(default_factory=lambda: generate_id("chk"))
    check_type: str = "state_match"
    description: str = ""
    check_fn: Callable[[Path, dict[str, Any]], bool] = field(
        default_factory=lambda: (lambda _ws, _state: True)
    )
    expected: Any = None
    actual: Any = None
    passed: bool = False


# ============================================================================
# VerificationResult
# ============================================================================


@dataclass
class VerificationResult:
    """Aggregate result of running all checks against a :class:`CompletionClaim`.

    This is the firewall's *output* — a tamper-evident record of what
    was verified, what passed, and what the final verdict is.

    Attributes:
        claim:            The original :class:`CompletionClaim` being verified.
        checks:           Ordered list of :class:`EnvironmentCheck` results.
        verdict:          The overall :class:`CompletionVerdict`.
        passed_count:     Number of checks that passed.
        failed_count:     Number of checks that failed.
        total_count:      Total checks evaluated.
        confidence:       Computed verification confidence ∈ [0, 1],
                          defined as ``passed_count / total_count``.
        evidence_hashes:  SHA-256 hex-digests of verified artifact files,
                          keyed by file path.
        verified_at:      Timestamp at which verification completed.
    """

    claim: CompletionClaim = field(default_factory=CompletionClaim)
    checks: list[EnvironmentCheck] = field(default_factory=list)
    verdict: CompletionVerdict = CompletionVerdict.INCOMPLETE
    passed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    confidence: float = 0.0
    evidence_hashes: dict[str, str] = field(default_factory=dict)
    verified_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ============================================================================
# AntiFabricationFirewall
# ============================================================================


class AntiFabricationFirewall:
    """Main firewall engine enforcing environment-verified completions.

    The firewall implements the Goal-Autopilot (Deng, 2026) discipline:
    no completion claim is accepted unless *every* registered
    :class:`EnvironmentCheck` independently confirms it.  This makes
    false "done" claims **structurally impossible** — the agent cannot
    fool the runtime by merely *saying* it finished.

    Lifecycle::

        fw = AntiFabricationFirewall(policy, workspace)
        fw.register_check(EnvironmentCheck(…))
        result = fw.verify_claim(claim, state)
        if fw.is_completion_allowed(result):
            # accept completion
        else:
            # reject / request remediation

    Args:
        policy:        A :class:`FirewallPolicy` governing thresholds.
        workspace_dir: Root directory of the agent's workspace (used as
                       the base path for file-system checks).
    """

    def __init__(self, policy: FirewallPolicy, workspace_dir: Path) -> None:
        self._policy = policy
        self._workspace_dir = workspace_dir
        self._checks: list[EnvironmentCheck] = []

        # Historical counters
        self._total_claims: int = 0
        self._genuine_claims: int = 0
        self._fabricated_claims: int = 0

        logger.info(
            "AntiFabricationFirewall initialised (workspace=%s, "
            "min_checks=%d, require_env=%s)",
            workspace_dir,
            policy.min_verification_checks,
            policy.require_environment_verification,
        )

    # -- check registration --------------------------------------------------

    def register_check(self, check: EnvironmentCheck) -> None:
        """Add an :class:`EnvironmentCheck` to the firewall's registry.

        Registered checks are evaluated in order during
        :meth:`verify_claim`.  Duplicate ``check_id`` values are
        rejected.

        Args:
            check: The check to register.

        Raises:
            ValueError: If a check with the same ``check_id`` already
                        exists.
        """
        if any(c.check_id == check.check_id for c in self._checks):
            raise ValueError(
                f"Check {check.check_id!r} is already registered"
            )
        self._checks.append(check)
        logger.info(
            "Firewall: registered check %s (%s)", check.check_id, check.check_type
        )

    # -- core verification ---------------------------------------------------

    def verify_claim(
        self, claim: CompletionClaim, state: dict[str, Any]
    ) -> VerificationResult:
        """Run all registered checks against *claim* and *state*.

        This is the primary entry point.  The method:

        1. Ensures at least ``policy.min_verification_checks`` checks
           are registered (otherwise the claim is ``UNVERIFIABLE``).
        2. Evaluates each check, capturing pass/fail and populating
           ``actual`` fields.
        3. Optionally computes SHA-256 hashes of claimed artifacts when
           ``policy.enable_hash_verification`` is ``True``.
        4. Derives the :class:`CompletionVerdict` from the results.

        Args:
            claim: The agent's completion claim.
            state: Current environment state dictionary.

        Returns:
            A fully populated :class:`VerificationResult`.
        """
        self._total_claims += 1

        # --- Insufficient checks guard ---
        if len(self._checks) < self._policy.min_verification_checks:
            logger.warning(
                "Firewall: only %d checks registered (need %d) — UNVERIFIABLE",
                len(self._checks),
                self._policy.min_verification_checks,
            )
            result = VerificationResult(
                claim=claim,
                checks=[],
                verdict=CompletionVerdict.UNVERIFIABLE,
                total_count=0,
                confidence=0.0,
            )
            return result

        # --- Execute checks ---
        passed = 0
        failed = 0
        evaluated_checks: list[EnvironmentCheck] = []

        for check in self._checks:
            try:
                check.passed = check.check_fn(self._workspace_dir, state)
            except Exception:
                logger.exception(
                    "Firewall: check %s raised an exception — treating as FAIL",
                    check.check_id,
                )
                check.passed = False

            if check.passed:
                passed += 1
            else:
                failed += 1
            evaluated_checks.append(check)
            logger.debug(
                "Firewall: check %s (%s) → %s",
                check.check_id,
                check.check_type,
                "PASS" if check.passed else "FAIL",
            )

        total = passed + failed
        confidence = passed / total if total > 0 else 0.0

        # --- Artifact hashes ---
        evidence_hashes: dict[str, str] = {}
        if self._policy.enable_hash_verification:
            artifact_paths = [
                self._workspace_dir / a for a in claim.claimed_artifacts
            ]
            evidence_hashes = self.compute_artifact_hashes(artifact_paths)

        # --- Derive verdict ---
        verdict = self._derive_verdict(
            claim, passed, failed, total, confidence
        )

        # --- Update historical counters ---
        if verdict == CompletionVerdict.GENUINE:
            self._genuine_claims += 1
        elif verdict == CompletionVerdict.FABRICATED:
            self._fabricated_claims += 1

        result = VerificationResult(
            claim=claim,
            checks=evaluated_checks,
            verdict=verdict,
            passed_count=passed,
            failed_count=failed,
            total_count=total,
            confidence=confidence,
            evidence_hashes=evidence_hashes,
        )

        logger.info(
            "Firewall: claim %s verdict=%s (passed=%d, failed=%d, "
            "confidence=%.2f)",
            claim.claim_id,
            verdict.name,
            passed,
            failed,
            confidence,
        )
        return result

    # -- convenience file / command helpers -----------------------------------

    def compute_artifact_hashes(
        self, file_paths: list[Path]
    ) -> dict[str, str]:
        """Compute SHA-256 hex-digests for a list of file paths.

        Files that do not exist or cannot be read are silently skipped
        (their absence should be caught by an ``EnvironmentCheck``).

        Args:
            file_paths: Absolute or workspace-relative paths.

        Returns:
            A dict mapping ``str(path)`` → SHA-256 hex-digest for each
            readable file.
        """
        hashes: dict[str, str] = {}
        for path in file_paths:
            abs_path = (
                path if path.is_absolute() else self._workspace_dir / path
            )
            if not abs_path.is_file():
                logger.debug("compute_artifact_hashes: %s not found", abs_path)
                continue
            try:
                sha = hashlib.sha256(abs_path.read_bytes()).hexdigest()
                hashes[str(path)] = sha
            except OSError:
                logger.warning(
                    "compute_artifact_hashes: failed to read %s", abs_path
                )
        return hashes

    def check_file_exists(self, path: Path) -> bool:
        """Return ``True`` if *path* exists under the workspace.

        Args:
            path: Absolute or workspace-relative path to check.
        """
        abs_path = (
            path if path.is_absolute() else self._workspace_dir / path
        )
        exists = abs_path.exists()
        logger.debug("check_file_exists(%s) → %s", abs_path, exists)
        return exists

    def check_file_content(
        self, path: Path, expected_patterns: list[str]
    ) -> bool:
        """Return ``True`` if *path* contains all *expected_patterns*.

        Each pattern is compiled as a regular expression and searched
        against the file's text content.

        Args:
            path:              Absolute or workspace-relative path.
            expected_patterns: Regex patterns that must all be found.
        """
        abs_path = (
            path if path.is_absolute() else self._workspace_dir / path
        )
        if not abs_path.is_file():
            return False
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning("check_file_content: cannot read %s", abs_path)
            return False

        for pattern in expected_patterns:
            if not re.search(pattern, content):
                logger.debug(
                    "check_file_content: pattern %r not found in %s",
                    pattern,
                    abs_path,
                )
                return False
        return True

    def check_command_output(self, command: str, expected: str) -> bool:
        """Run *command* in a subprocess and check stdout contains *expected*.

        The command is run with a 30-second timeout in the workspace
        directory.  ``stderr`` is captured but not checked.

        Args:
            command:  Shell command to execute.
            expected: Substring that must appear in stdout.

        Returns:
            ``True`` when *expected* is found in the command's stdout.
        """
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self._workspace_dir),
            )
            found = expected in proc.stdout
            logger.debug(
                "check_command_output(%r): returncode=%d, match=%s",
                command,
                proc.returncode,
                found,
            )
            return found
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("check_command_output(%r) failed: %s", command, exc)
            return False

    # -- final gate ----------------------------------------------------------

    def is_completion_allowed(self, result: VerificationResult) -> bool:
        """Determine whether the claim may be accepted as complete.

        The claim is allowed only when:
          - The verdict is ``GENUINE``.
          - If ``policy.block_unverifiable_claims`` is ``True``, the
            verdict must not be ``UNVERIFIABLE``.

        Args:
            result: The :class:`VerificationResult` from
                    :meth:`verify_claim`.
        """
        if result.verdict == CompletionVerdict.GENUINE:
            return True
        if (
            result.verdict == CompletionVerdict.UNVERIFIABLE
            and not self._policy.block_unverifiable_claims
        ):
            # Policy allows unverifiable claims to pass (unusual, but
            # configurable for dev/testing).
            return True
        return False

    # -- aggregate statistics ------------------------------------------------

    @property
    def total_claims(self) -> int:
        """Total number of completion claims processed."""
        return self._total_claims

    @property
    def genuine_claims(self) -> int:
        """Number of claims verified as genuine."""
        return self._genuine_claims

    @property
    def fabricated_claims(self) -> int:
        """Number of claims detected as fabricated."""
        return self._fabricated_claims

    @property
    def fabrication_rate(self) -> float:
        """Fraction of processed claims that were fabricated ∈ [0, 1].

        Returns 0.0 when no claims have been processed.
        """
        if self._total_claims == 0:
            return 0.0
        return self._fabricated_claims / self._total_claims

    # -- internals -----------------------------------------------------------

    def _derive_verdict(
        self,
        claim: CompletionClaim,
        passed: int,
        failed: int,
        total: int,
        confidence: float,
    ) -> CompletionVerdict:
        """Derive the :class:`CompletionVerdict` from check results.

        Decision matrix:
          - All checks pass                        → ``GENUINE``
          - Any check fails AND artifact evidence
            is required but missing                → ``FABRICATED``
          - Some checks fail with partial evidence → ``INCOMPLETE``
          - Cannot determine                       → ``UNVERIFIABLE``
        """
        if total == 0:
            return CompletionVerdict.UNVERIFIABLE

        if failed == 0:
            return CompletionVerdict.GENUINE

        # When artifact evidence is required but some checks fail,
        # distinguish between fabrication and partial progress.
        if self._policy.require_artifact_evidence:
            # If the agent is highly confident but checks disagree →
            # likely fabrication.
            if claim.agent_confidence > 0.8 and confidence < 0.5:
                return CompletionVerdict.FABRICATED

        # Some checks failed but not conclusive fabrication.
        if confidence >= 0.5:
            return CompletionVerdict.INCOMPLETE

        return CompletionVerdict.FABRICATED
