"""
State-Aware Durable Runtime (SADR)
===================================

A unified runtime architecture for reliable long-horizon AI agents.

Externalizes persistent agent state from bounded reasoning context,
governs memory evolution through validated write paths, enforces
behavioral contracts at execution time, and supports semantics-aware
checkpointing and rollback for recovery.

Core Components:
    - StateStore:       Hierarchical State Trees (MAGE) for externalized durable state
    - MEALoop:          Manage-Execute-Audit cycle with strict role isolation
    - ContractEngine:   Pre/In/Post action gates for behavioral enforcement
    - MemoryGovernor:   Write-path validation, anti-poisoning, selective decay
    - RecoveryEngine:   Semantics-aware checkpointing & branch-isolated rollback
    - Firewall:         Anti-fabrication verification of completion claims
    - LineageLogger:    Append-only causal audit trail

References:
    Bhardwaj (2026) - Agent Behavioral Contracts
    Ran et al. (2026) - CaveAgent: Stateful Runtime Operators
    Brady (2026) - Springdrift: Auditable Persistent Runtime
    Deng (2026) - Goal-Autopilot: Anti-Fabrication Firewall
    Lam et al. (2026) - SSGM Framework
    Wu et al. (2026) - Crab: Semantics-Aware Checkpoint/Restore
"""

__version__ = "0.1.0"
__author__ = "Nishita Singh"
