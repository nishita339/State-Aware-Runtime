"""
CLI Interface for the State-Aware Durable Runtime.

Provides command-line access to:
    - Running agents on long-horizon tasks
    - Inspecting saved sessions and state
    - Viewing lineage audit logs
    - Benchmarking with built-in evaluation
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import click
except ImportError:
    # Fallback if click is not installed
    click = None  # type: ignore

from state_aware_runtime.config import (
    ActionProposal,
    ActionResult,
    RuntimeConfig,
    SubtaskContract,
)
from state_aware_runtime.firewall import EnvironmentCheck
from state_aware_runtime.mea_loop import AgentInterface, ToolExecutor
from state_aware_runtime.runtime import StatefulRuntime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ============================================================================
# Demo Agent (for testing without an LLM)
# ============================================================================


class DemoAgent:
    """
    A simple deterministic agent for testing the runtime.

    This agent follows a fixed sequence of actions to demonstrate
    the MEA loop, contract enforcement, and recovery mechanics
    without requiring any LLM API calls.
    """

    def __init__(self) -> None:
        self._step = 0
        self._subtask_step = 0

    def plan_subtasks(
        self,
        objective: str,
        current_state: dict[str, Any],
        history_summary: str,
    ) -> list[SubtaskContract]:
        """Create simple demo subtasks."""
        return [
            SubtaskContract(
                objective=f"Step 1: Analyze requirements for '{objective[:50]}'",
                preconditions=["workspace exists"],
                postconditions=["requirements_analyzed = true"],
                invariants=["workspace exists"],
                verification_criteria=["Analysis document exists"],
                max_actions=5,
            ),
            SubtaskContract(
                objective=f"Step 2: Implement solution for '{objective[:50]}'",
                preconditions=["requirements_analyzed = true"],
                postconditions=["implementation_complete = true"],
                invariants=["workspace exists"],
                verification_criteria=["Source code files exist"],
                max_actions=10,
            ),
            SubtaskContract(
                objective=f"Step 3: Verify and test '{objective[:50]}'",
                preconditions=["implementation_complete = true"],
                postconditions=["tests_passing = true"],
                invariants=["workspace exists"],
                verification_criteria=["All tests pass"],
                max_actions=5,
            ),
        ]

    def propose_action(
        self, subtask: SubtaskContract, context: dict[str, Any]
    ) -> ActionProposal:
        """Propose a demo action."""
        self._subtask_step += 1
        return ActionProposal(
            action_type="tool_call",
            tool_name="demo_tool",
            parameters={"step": self._subtask_step, "subtask": subtask.objective[:50]},
            rationale=f"Executing step {self._subtask_step} of subtask",
        )

    def claim_completion(
        self, subtask: SubtaskContract, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Claim completion after a few actions."""
        if self._subtask_step >= 2:
            self._subtask_step = 0
            return {
                "completed": True,
                "evidence": {"demo": True},
                "artifacts": ["demo_output.txt"],
                "confidence": 0.9,
            }
        return {"completed": False}


class DemoToolExecutor:
    """A simple tool executor for demo/testing purposes."""

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace = workspace_dir
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, Any] = {
            "workspace exists": True,
            "requirements_analyzed": False,
            "implementation_complete": False,
            "tests_passing": False,
        }
        self._action_count = 0

    def execute(self, action: ActionProposal) -> ActionResult:
        """Execute a demo action."""
        self._action_count += 1

        # Simulate state transitions
        if "Step 1" in action.parameters.get("subtask", ""):
            self._state["requirements_analyzed"] = True
            self._state["requirements_analyzed = true"] = True
        elif "Step 2" in action.parameters.get("subtask", ""):
            self._state["implementation_complete"] = True
            self._state["implementation_complete = true"] = True
        elif "Step 3" in action.parameters.get("subtask", ""):
            self._state["tests_passing"] = True
            self._state["tests_passing = true"] = True

        return ActionResult(
            action_id=action.action_id,
            success=True,
            output=f"Demo action {self._action_count} completed successfully",
            state_diff=dict(self._state),
            tokens_used=100,
        )

    def get_environment_state(self) -> dict[str, Any]:
        """Return current environment state."""
        return dict(self._state)


# ============================================================================
# CLI Commands
# ============================================================================


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the CLI."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    """Main CLI entry point."""
    if click is None:
        _run_without_click()
        return

    cli()


@click.group() if click else lambda f: f  # type: ignore
def cli() -> None:
    """State-Aware Durable Runtime (SADR) for Long-Horizon AI Agents."""
    pass


if click:

    @cli.command()
    @click.option("--workspace", "-w", default="./workspace", help="Workspace directory")
    @click.option("--state-dir", "-s", default="./state", help="State persistence directory")
    @click.option("--log-dir", "-l", default="./logs", help="Log directory")
    @click.option("--log-level", default="INFO", help="Logging level")
    @click.option("--objective", "-o", default="Demo task", help="Task objective")
    def demo(
        workspace: str,
        state_dir: str,
        log_dir: str,
        log_level: str,
        objective: str,
    ) -> None:
        """Run a demo with the built-in test agent."""
        setup_logging(log_level)

        config = RuntimeConfig(
            workspace_dir=Path(workspace),
            state_dir=Path(state_dir),
            log_dir=Path(log_dir),
        )

        runtime = StatefulRuntime(config)
        # Register firewall verification checks so the demo claims can be verified
        runtime.firewall.register_check(EnvironmentCheck(
            description="Verify requirements analyzed",
            check_fn=lambda ws, state: bool(state.get("requirements_analyzed = true") or state.get("requirements_analyzed")),
        ))
        runtime.firewall.register_check(EnvironmentCheck(
            description="Verify test suite passing",
            check_fn=lambda ws, state: bool(state.get("tests_passing = true") or state.get("tests_passing")),
        ))

        agent = DemoAgent()
        tool_executor = DemoToolExecutor(config.workspace_dir)

        click.echo(f"\n{'='*60}")
        click.echo(f"  State-Aware Durable Runtime — Demo")
        click.echo(f"  Objective: {objective}")
        click.echo(f"{'='*60}\n")

        result = runtime.run(agent, tool_executor, objective)

        click.echo(f"\n{'='*60}")
        click.echo(f"  Result: {'SUCCESS ✓' if result.success else 'FAILED ✗'}")
        click.echo(f"  Actions: {result.total_actions}")
        click.echo(f"  Tokens: {result.total_tokens}")
        click.echo(f"  Time: {result.total_time_ms:.0f}ms")
        click.echo(f"  Completion Verified: {result.completion_verified}")
        click.echo(f"{'='*60}\n")

        # Print metrics
        metrics = runtime.get_metrics()
        click.echo("Metrics:")
        click.echo(json.dumps(metrics.to_dict(), indent=2))

    @cli.command()
    @click.option("--state-dir", "-s", default="./state", help="State persistence directory")
    def sessions(state_dir: str) -> None:
        """List all saved sessions."""
        from state_aware_runtime.state_store import StateStore

        store = StateStore(Path(state_dir))
        session_ids = store.list_sessions()

        if not session_ids:
            click.echo("No saved sessions found.")
            return

        click.echo(f"Found {len(session_ids)} sessions:")
        for sid in session_ids:
            click.echo(f"  • {sid}")

    @cli.command()
    @click.argument("session_id")
    @click.option("--log-dir", "-l", default="./logs", help="Log directory")
    def lineage(session_id: str, log_dir: str) -> None:
        """View lineage log for a session."""
        from state_aware_runtime.lineage import LineageLogger

        log_path = Path(log_dir) / f"lineage_{session_id}.jsonl"
        if not log_path.exists():
            click.echo(f"No lineage log found for session '{session_id}'")
            return

        logger_inst = LineageLogger(Path(log_dir), session_id)
        summary = logger_inst.get_session_summary()

        click.echo(f"\nLineage Summary for {session_id}:")
        click.echo(json.dumps(summary, indent=2))

    @cli.command()
    @click.argument("session_id")
    @click.option("--state-dir", "-s", default="./state", help="State persistence directory")
    def inspect(session_id: str, state_dir: str) -> None:
        """Inspect state tree for a session."""
        from state_aware_runtime.state_store import StateStore

        store = StateStore(Path(state_dir))
        try:
            tree = store.load(session_id)
            stats = tree.get_stats()
            click.echo(f"\nState Tree for {session_id}:")
            click.echo(json.dumps(stats, indent=2))
        except FileNotFoundError:
            click.echo(f"No saved state for session '{session_id}'")


def _run_without_click() -> None:
    """Fallback CLI without click dependency."""
    setup_logging("INFO")

    print("\n" + "="*60)
    print("  State-Aware Durable Runtime — Demo (no click)")
    print("="*60 + "\n")

    config = RuntimeConfig(
        workspace_dir=Path("./workspace"),
        state_dir=Path("./state"),
        log_dir=Path("./logs"),
    )

    runtime = StatefulRuntime(config)
    runtime.firewall.register_check(EnvironmentCheck(
        description="Verify requirements analyzed",
        check_fn=lambda ws, state: bool(state.get("requirements_analyzed = true") or state.get("requirements_analyzed")),
    ))
    runtime.firewall.register_check(EnvironmentCheck(
        description="Verify test suite passing",
        check_fn=lambda ws, state: bool(state.get("tests_passing = true") or state.get("tests_passing")),
    ))

    agent = DemoAgent()
    tool_executor = DemoToolExecutor(config.workspace_dir)

    result = runtime.run(agent, tool_executor, "Demo long-horizon task")

    print(f"\nResult: {'SUCCESS ✓' if result.success else 'FAILED ✗'}")
    print(f"Actions: {result.total_actions}")
    print(f"Tokens: {result.total_tokens}")
    print(f"Time: {result.total_time_ms:.0f}ms")

    metrics = runtime.get_metrics()
    print("\nMetrics:")
    print(json.dumps(metrics.to_dict(), indent=2))


if __name__ == "__main__":
    main()
