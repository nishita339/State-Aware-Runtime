"""
Example: Running the State-Aware Durable Runtime with a demo agent.

This example demonstrates the full runtime lifecycle:
    1. Configure the runtime with policies
    2. Register behavioral contracts
    3. Run a demo agent through the MEA loop
    4. Inspect metrics, lineage, and state tree

Run with: py examples/demo_run.py
"""

import json
import sys
from pathlib import Path

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from state_aware_runtime.cli import DemoAgent, DemoToolExecutor
from state_aware_runtime.config import RuntimeConfig, ContractPolicy, MemoryPolicy
from state_aware_runtime.contracts import BehavioralContract, ContractClause
from state_aware_runtime.runtime import StatefulRuntime


def main():
    print("=" * 70)
    print("  State-Aware Durable Runtime — Full Demo")
    print("  Unified runtime for reliable long-horizon AI agents")
    print("=" * 70)

    # ---- Step 1: Configure Runtime ----
    config = RuntimeConfig(
        workspace_dir=Path("./demo_workspace"),
        state_dir=Path("./demo_state"),
        log_dir=Path("./demo_logs"),
        contract_policy=ContractPolicy(
            max_drift_score=0.27,
            hard_constraint_mode="block",
        ),
        memory_policy=MemoryPolicy(
            enable_write_validation=True,
            episodic_decay_rate=0.15,
        ),
    )

    runtime = StatefulRuntime(config)

    # ---- Step 2: Register Behavioral Contracts & Firewall Checks ----
    safety_contract = BehavioralContract(name="safety_rules")
    safety_contract.add_clause(ContractClause(
        clause_type="invariant",
        description="Workspace must always exist",
        check_fn=lambda state: True,  # Always passes for demo
        severity="hard",
    ))
    safety_contract.add_clause(ContractClause(
        clause_type="forbidden",
        description="Never execute rm -rf",
        check_fn=lambda state: "rm -rf" not in str(state),
        severity="hard",
    ))
    runtime.register_contract(safety_contract)

    # Register Anti-Fabrication Firewall Environment Checks
    # (Goal-Autopilot verification: ensures claims match reality)
    from state_aware_runtime.firewall import EnvironmentCheck
    runtime.firewall.register_check(EnvironmentCheck(
        description="Verify requirements analyzed",
        check_fn=lambda ws, state: state.get("requirements_analyzed = true", False) or state.get("requirements_analyzed", False),
    ))
    runtime.firewall.register_check(EnvironmentCheck(
        description="Verify test suite passing",
        check_fn=lambda ws, state: state.get("tests_passing = true", False) or state.get("tests_passing", False),
    ))

    print("\n[1] Runtime configured with behavioral contracts & firewall")
    print(f"    - Drift threshold: D* < {config.contract_policy.max_drift_score}")
    print(f"    - Memory decay rate (episodic): {config.memory_policy.episodic_decay_rate}")
    print(f"    - Contracts registered: 1 (safety_rules)")
    print(f"    - Firewall verification checks registered: 2")

    # ---- Step 3: Create Agent and Tool Executor ----
    agent = DemoAgent()
    tool_executor = DemoToolExecutor(config.workspace_dir)

    print("\n[2] Agent and tool executor initialized")

    # ---- Step 4: Run the MEA Loop ----
    print("\n[3] Running MEA loop...")
    print("    Manager -> Executor -> Auditor -> Commit/Recover\n")

    result = runtime.run(
        agent=agent,
        tool_executor=tool_executor,
        objective="Build a complete web application with user authentication",
    )

    # ---- Step 5: Display Results ----
    status = "SUCCESS ✓" if result.success else "FAILED ✗"
    print(f"\n{'=' * 70}")
    print(f"  Result: {status}")
    print(f"{'=' * 70}")
    print(f"  Total Actions:        {result.total_actions}")
    print(f"  Total Tokens:         {result.total_tokens}")
    print(f"  Time:                 {result.total_time_ms:.0f}ms")
    print(f"  Completion Verified:  {result.completion_verified}")
    print(f"  Subtasks Completed:   {len(result.subtask_results)}")

    # ---- Step 6: Display Metrics ----
    metrics = runtime.get_metrics()
    m = metrics.to_dict()

    print(f"\n  --- Drift Control ---")
    print(f"  Peak Drift:           {m['drift']['peak']:.4f}")
    print(f"  Drift Violations:     {m['drift']['violations']}")

    print(f"\n  --- Contract Compliance ---")
    print(f"  Total Checks:         {m['contracts']['total_checks']}")
    print(f"  Hard Violations:      {m['contracts']['hard_violations']}")
    print(f"  Compliance Rate:      {m['contracts']['compliance_rate']:.1%}")

    print(f"\n  --- Recovery ---")
    print(f"  Failures:             {m['recovery']['failures']}")
    print(f"  Successful Recoveries:{m['recovery']['successful']}")
    print(f"  Rollbacks:            {m['recovery']['rollbacks']}")

    print(f"\n  --- Memory Governance ---")
    print(f"  Writes:               {m['memory']['writes']}")
    print(f"  Rejections:           {m['memory']['rejections']}")
    print(f"  Quarantines:          {m['memory']['quarantines']}")

    print(f"\n  --- Anti-Fabrication ---")
    print(f"  Claims:               {m['anti_fabrication']['claims']}")
    print(f"  Genuine:              {m['anti_fabrication']['genuine']}")
    print(f"  Fabricated:           {m['anti_fabrication']['fabricated']}")

    # ---- Step 7: State Tree ----
    tree_stats = runtime.get_state_tree_stats()
    print(f"\n  --- State Tree ---")
    print(f"  Total Nodes:          {tree_stats.get('total_nodes', 0)}")
    print(f"  Active Depth:         {tree_stats.get('active_depth', 0)}")
    print(f"  Failed Branches:      {tree_stats.get('failed_branches', 0)}")

    # ---- Step 8: Lineage ----
    lineage = runtime.get_lineage_summary()
    print(f"\n  --- Lineage Audit Trail ---")
    print(f"  Total Events:         {lineage.get('total_events', 0)}")
    print(f"  Duration:             {lineage.get('duration_seconds', 0):.2f}s")

    print(f"\n{'=' * 70}")
    print("  Demo complete. Files saved to:")
    print(f"    State: {config.state_dir}")
    print(f"    Logs:  {config.log_dir}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
