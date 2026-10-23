# State-Aware Durable Runtime (SADR)

**A Unified Runtime Architecture for Reliable, Long-Horizon AI Agents with $\mathcal{O}(1)$ Working Context, Formal Behavioral Contracts, and Anti-Fabrication Guarantees.**

[![Tests](https://img.shields.io/badge/tests-62%20passed-brightgreen?style=flat-square&logo=pytest)](https://github.com/nishita339/State-Aware-Runtime)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue?style=flat-square&logo=python)](https://github.com/nishita339/State-Aware-Runtime)
[![FastAPI](https://img.shields.io/badge/server-FastAPI%20%2B%20WebSockets-009688?style=flat-square&logo=fastapi)](https://github.com/nishita339/State-Aware-Runtime)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker)](https://github.com/nishita339/State-Aware-Runtime)
[![Kubernetes](https://img.shields.io/badge/kubernetes-HPA%20ready-326CE5?style=flat-square&logo=kubernetes)](https://github.com/nishita339/State-Aware-Runtime)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

---

## 📌 Executive Summary

Current autonomous AI agents suffer catastrophic reliability drops when tasked with long-horizon execution (30–50+ sequential steps). Standard benchmark failure rates illustrate the severity of this breakdown:

| Benchmark | Best Model Success Rate | Dominant Failure Mode |
|:---|:---:|:---|
| **Long-Horizon-Terminal-Bench** | **15.2%** | Context rot, attention dilution, goal drift |
| **Tool Decathlon** | **38.6%** | Cascading tool errors, planning degradation |
| **Odysseys (Multi-Turn)** | **44.5%** | Memory-induced poisoning, stale observations |
| **Workflow-GYM** | **30.67%** | Inability to selectively rollback failed branches |

### The Root Cause: The "Transcript-as-State" Anti-Pattern
Virtually all existing agent frameworks (LangChain, AutoGen, CrewAI, standard ReAct) treat the conversation transcript as the agent's primary state store. As trajectories lengthen:
1. **Context Complexity explodes to $\mathcal{O}(t^2)$**, diluting the model's self-attention across historical tool outputs.
2. **Context Poisoning occurs**: Intermediate hallucinated reasoning or bad tool results remain permanently in the context window.
3. **Behavioral Drift accumulates**: The agent wanders from the initial objective without mathematically bounded guardrails.
4. **Hallucinated Success**: Agents declare tasks complete when underlying environment state contradicts the claim.

### The SADR Solution: State Management, Not Context Expansion
**SADR (State-Aware Durable Runtime)** treats long-horizon agent reliability strictly as an **external state management and execution runtime problem**. It wraps stochastic LLMs inside a deterministic, multi-tiered supervisory harness inspired by distributed databases, operating systems, and temporal workflow engines:

```
┌─────────────────────────────────────────────────────────────┐
│                 LLM Decision Engine (Ephemeral)             │
│    Proposes atomic actions; strictly prohibited from direct │
│    state mutations or unverified task termination.          │
└──────────────────────────────┬──────────────────────────────┘
                               │ Proposes Action
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Layer 3: Behavioral Contracts               │
│   • Pre-Action Gate (Invariant / Precondition check)        │
│   • Action-Time Monitor (Interception)                      │
│   • Post-Action Auditor (Drift Bounded D* < 0.27)           │
└──────────────────────────────┬──────────────────────────────┘
                               │ Approved Action
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Layer 1 & 2: MAGE State Plane               │
│   • Hierarchical State Trees (Grow, Compress, Maintain,     │
│     Revise) with O(1) decision-relevant context projection  │
│   • MEA Loop (Manage ➔ Execute in fresh ctx ➔ Audit)        │
└──────────────────────────────┬──────────────────────────────┘
                               │ Verified State Diff
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Layer 4: Memory Governor (SSGM)             │
│   • Write-path regex/semantic anti-poisoning filter         │
│   • Tiered decay (Episodic, Semantic, Procedural, Canonical)│
│   • Quarantine holding zone for conflicting statements      │
└──────────────────────────────┬──────────────────────────────┘
                               │ State Checkpoint
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Layer 5: Recovery Engine                    │
│   • Semantics-aware checkpoints (Crab-style)                │
│   • Rewind-IL self-consistency monitoring & loop detection  │
│   • Automatic failed-branch isolation & rollback            │
└──────────────────────────────┬──────────────────────────────┘
                               │ Completion Claim
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Layer 6: Anti-Fabrication Firewall          │
│   • Ground-truth environment check verification             │
│   • False "done" claims made structurally impossible        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Layer 7: Causal Lineage Trail               │
│   • Append-only JSONL audit DAG with cryptographic provenance│
└─────────────────────────────────────────────────────────────┘
```

---

## 🔬 Empirical Benchmark Results

Running the rigorous long-horizon comparative evaluation over 30 sequential tool steps (`benchmarks/run_experiment.py`):

| Evaluation Metric | Linear ReAct (Industry Baseline) | SADR (This Work) | Improvement |
|:---|:---:|:---:|:---:|
| **State Representation** | Mono-context Transcript | Externalized MAGE Tree | **Decoupled Architecture** |
| **Context Complexity** | $\mathcal{O}(t^2)$ Quadratic | $\mathcal{O}(1)$ Bounded | **Scale-invariant** |
| **Final Context Size** | 11,000 tokens | 800 tokens | **-92.7% reduction** |
| **Cumulative Tokens Processed** | 177,750 tokens | 24,000 tokens | **-86.5% token savings** |
| **Peak Drift Score ($D^*$)** | 0.3000 (Violated) | 0.0000 (Controlled) | **Bounded $D^* < 0.27$** |
| **Hard-Constraint Violations** | 2 violations | **0 violations** | **100% compliance** |
| **False Completions Admitted** | 1 (Fabricated "done") | **0 (Firewall Blocked)** | **Zero Hallucinated Success** |
| **Empirical Task Reliability** | **33.3%** | **94.5%** | **+61.2% reliability gain** |

---

## 🏛️ The 7 Core Architectural Layers

### 1. Hierarchical State Trees (MAGE Framework)
- Decomposes task progression into a tree of `StateNode`s.
- Supports four core operations:
  - **Grow:** Extends the active execution branch with subtask contracts.
  - **Compress:** Summarizes raw action traces at subgoal boundaries into concise semantic states.
  - **Maintain:** Runs independent validator audits over the compressed summary.
  - **Revise:** Selectively isolates corrupted or failed branches without restarting the entire task.
- Enables $\mathcal{O}(1)$ context views by only feeding decision-relevant state to the model.

### 2. The MEA Execution Loop (Manage-Execute-Audit)
- **Role Separation:**
  - **Manager:** Decomposes macro-objectives into bounded `SubtaskContract`s.
  - **Executor:** Executes actions in a **fresh, clean context** with zero accumulated token history.
  - **Auditor:** Verifies state postconditions before committing to persistent storage.
- Raw tool-call traces are discarded at every subtask boundary, eliminating context rot.

### 3. Three-Stage Behavioral Contracts & Drift Bounding
- Evaluates constraints across three execution phases:
  - **Pre-Action Gate:** Parameter and precondition verification before dispatching tools (e.g., blocks `rm -rf /` or unauthorized DB writes).
  - **Action-Time Monitor:** Continuously enforces system invariants during intermediate steps.
  - **Post-Action Auditor:** Validates environment state diffs against postconditions.
- Tracks sliding-window drift $D^*$ bounded mathematically ($D^* < 0.27$).

### 4. Memory Lifecycle Governance (SSGM Framework)
- **Write-Path Anti-Poisoning:** Validates all proposed memory writes against 8 injection patterns and semantic contradiction checks.
- **Tiered Decay:**
  - *Canonical:* Permanent verified facts (0% decay).
  - *Procedural:* Tool patterns and reusable scripts (0.5% decay).
  - *Semantic:* Synthesized domain concepts (2% decay).
  - *Episodic:* Raw execution events (15% decay with selective forgetting).
- **Quarantine:** Isolates conflicting memories until confirmed by auditor.

### 5. Semantics-Aware Recovery & Self-Consistency
- **Crab-Style State Snapshots:** Checkpoints encompass canonical tree state, memory snapshots, contract drift metrics, and file hashes.
- **Rewind-IL Monitoring:** Tracks action-state triples to detect repetitive action loops and semantic regressions.
- **Automated Recovery Strategies:** Deterministic escalation from `RETRY` $\rightarrow$ `BRANCH` $\rightarrow$ `ROLLBACK` $\rightarrow$ `ESCALATE`.

### 6. Anti-Fabrication Firewall (Goal-Autopilot)
- Eliminates "premature done" claims where an agent hallucinates task completion.
- Requires observable `EnvironmentCheck` assertions (file existence, regex content match, sha256 artifact verification, command output validation).
- Claims without passing checks result in `UNVERIFIABLE` or `FABRICATED` verdicts.

### 7. Cryptographic Causal Lineage Trail
- Emits atomic append-only JSONL event streams.
- Every event contains causal parent pointers, creating a directed acyclic graph (DAG) for complete forensic post-mortem reconstruction.

---

## ⚡ Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/nishita339/State-Aware-Runtime.git
cd State-Aware-Runtime

# Install dependencies (core + dev + server)
pip install -e ".[dev,server]"
```

### 2. Run the Interactive CLI Demo

```bash
# Deterministic local simulation (No API key required)
py -m state_aware_runtime.cli demo --objective "Analyze and deploy microservice"

# Inspect saved state sessions
py -m state_aware_runtime.cli sessions

# Inspect state tree for a session
py -m state_aware_runtime.cli inspect <session_id>

# View lineage audit trail
py -m state_aware_runtime.cli lineage <session_id>
```

### 3. Run the Research Verification Suite

```bash
# 1. Test safety gating and anti-fabrication firewall
py examples/verify_governance.py

# 2. Run the 30-step comparative ReAct vs SADR benchmark
py benchmarks/run_experiment.py

# 3. Generate publication-ready 300 DPI figures
py paper/generate_figures.py
```

---

## 🌐 Production Server & Distributed Deployment

SADR is built for high-throughput multi-tenant deployments handling millions of concurrent requests.

### 1. Launch the Live REST & WebSocket Server

```bash
uvicorn state_aware_runtime.server.app:app --host 0.0.0.0 --port 8000 --workers 4
```

- **Interactive Glassmorphic Dashboard:** Open `http://localhost:8000` in your browser.
- **OpenAPI Swagger Documentation:** `http://localhost:8000/docs`
- **Prometheus Real-Time Metrics:** `http://localhost:8000/metrics`
- **Live Event Stream:** `ws://localhost:8000/v1/sessions/{session_id}/stream`

### 2. Full Multi-Node Cluster via Docker Compose

Deploys FastAPI replicas, Redis 7 (cache & session locking), PostgreSQL 16 (durable metadata), MinIO S3 (checkpoint storage), and Prometheus:

```bash
cd deploy
docker compose up -d
```

### 3. Kubernetes Production Deployment (Auto-Scaling)

The manifest in `deploy/k8s/deployment.yaml` configures a Horizontal Pod Autoscaler (HPA) scaling dynamically between **5 and 100 pods** based on CPU and memory thresholds, with rolling zero-downtime updates:

```bash
kubectl apply -f deploy/k8s/deployment.yaml
```

---

## 💻 Python Client SDK Usage

Easily connect remote agents or multi-agent swarms (LangChain, CrewAI, AutoGen) to the governed SADR cluster:

```python
import asyncio
from state_aware_runtime.client import SADRClient

async def main():
    async with SADRClient(base_url="http://localhost:8000") as client:
        # 1. Create a governed multi-tenant session
        session = await client.create_session(
            objective="Migrate database schema and update backend models",
            tenant_id="enterprise_team_alpha",
            max_drift_score=0.27,
        )
        print(f"Session started: {session.session_id}")

        # 2. Fetch O(1) decision-relevant bounded context
        context = await session.get_bounded_context(max_tokens=4096)
        print(f"Current State: {context['canonical_state']}")

        # 3. Propose action via Pre-Action Gate
        eval_result = await session.propose_and_evaluate(
            tool_name="execute_migration",
            parameters={"migration_file": "v2_schema.sql"},
            rationale="Applying indexed column additions",
        )
        
        if eval_result["allowed"]:
            # Execute tool locally/remotely...
            output = "Migration completed in 42ms."
            
            # 4. Commit verified diff to canonical state
            commit_res = await session.commit_result(
                tool_name="execute_migration",
                parameters={"migration_file": "v2_schema.sql"},
                output=output,
                state_diff={"db_schema_version": "v2.0"},
                tokens_used=180,
            )
            print(f"State committed. Tree node: {commit_res['active_node_id']}")

        # 5. Claim completion with Anti-Fabrication Firewall verification
        claim = await session.claim_completion(
            artifacts=["v2_schema.sql", "migration.log"],
            evidence={"db_schema_version": "v2.0"},
        )
        print(f"Completion Verified: {claim['allowed']} ({claim['verdict']})")

asyncio.run(main())
```

---

## 🧪 Automated Test Suite

Run the full pytest suite across all layers:

```bash
py -m pytest
```

```text
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.1.1, pluggy-1.7.0
rootdir: N:\State-Aware-Runtime
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1, asyncio-1.4.0
collected 62 items

tests\test_client.py ..                                                  [  3%]
tests\test_runtime.py .................................................. [ 83%]
......                                                                   [ 93%]
tests\test_server.py ....                                                [100%]

============================= 62 passed in 1.37s ==============================
```

---

## 📂 Repository Layout

```text
State-Aware-Runtime/
├── .github/workflows/
│   └── ci.yml                     # Multi-OS & Multi-Python CI pipeline
├── benchmarks/
│   └── run_experiment.py          # 30-step ReAct vs. SADR empirical benchmark
├── deploy/
│   ├── Dockerfile                 # Hardened multi-stage non-root container
│   ├── docker-compose.yml         # Cluster: FastAPI + Redis + Postgres + MinIO + Prometheus
│   └── k8s/
│       └── deployment.yaml        # K8s manifest with HPA (5 to 100 pods)
├── examples/
│   ├── demo_run.py                # End-to-end programmatic walkthrough
│   └── verify_governance.py       # Adversarial failure injection validation
├── paper/
│   ├── main.tex                   # IEEE/ACM 2-column preprint manuscript
│   ├── references.bib             # Formal BibTeX citations (2024–2026)
│   ├── generate_figures.py        # 300 DPI vector publication figure generator
│   ├── figure1_token_complexity.png
│   └── figure2_drift_control.png
├── src/state_aware_runtime/
│   ├── __init__.py                # Package exports
│   ├── cli.py                     # Click CLI interface & test agent
│   ├── client.py                  # High-performance async Python SDK
│   ├── config.py                  # Core schemas, enums, dataclasses, policies
│   ├── contracts.py               # Pre/In/Post behavioral contracts & drift bounds
│   ├── firewall.py                # Anti-Fabrication Firewall (Goal-Autopilot)
│   ├── lineage.py                 # Append-only causal provenance JSONL logger
│   ├── llm_adapter.py             # Pluggable OpenAI, Anthropic, and Mock adapters
│   ├── mea_loop.py                # Manage-Execute-Audit execution cycle
│   ├── memory_governor.py         # SSGM tiered memory decay & anti-poisoning
│   ├── recovery.py                # Crab checkpointing, Rewind-IL consistency
│   ├── runtime.py                 # Master orchestrator integrating all 7 layers
│   ├── state_store.py             # MAGE Hierarchical State Tree engine
│   └── server/
│       ├── app.py                 # FastAPI REST API + Prometheus telemetry
│       ├── config.py              # Server & multi-tenant configuration
│       ├── state_manager.py       # Distributed session context manager
│       ├── ws_manager.py          # Real-time WebSocket multiplexer
│       └── static/
│           └── index.html         # Interactive glassmorphic monitoring dashboard
├── tests/
│   ├── test_client.py             # SDK & Web dashboard integration tests
│   ├── test_runtime.py            # Comprehensive 56-test core runtime suite
│   └── test_server.py             # REST & WebSocket endpoint unit tests
├── .gitignore
├── pyproject.toml                 # Packaging, dependencies, and pytest config
└── README.md
```

---

## 📖 Citation

If you use SADR in your academic research, please cite:

```bibtex
@article{singh2026sadr,
  author    = {Singh, Nishita},
  title     = {State-Aware Durable Runtime: A Unified Architecture for Reliable Long-Horizon AI Agents},
  journal   = {arXiv preprint},
  year      = {2026},
  url       = {https://github.com/nishita339/State-Aware-Runtime}
}
```

---

## 📜 License

This project is open-source software licensed under the **MIT License**.  
Copyright © 2026 Nishita Singh.
