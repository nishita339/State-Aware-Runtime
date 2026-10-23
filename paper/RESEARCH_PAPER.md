# State-Aware Durable Runtime: A Governed Execution Engine for Reliable Long-Horizon AI Agents

**Author:** Nishita Singh  
**Affiliation:** Department of Computer Science and Engineering  
**Email:** nishita.23cse425@rtu.ac.in  
**Code Repository:** [https://github.com/nishita339/State-Aware-Runtime](https://github.com/nishita339/State-Aware-Runtime)  

---

## Abstract

Autonomous agent frameworks driven by Large Language Models (LLMs) experience acute reliability collapses when tasked with long-horizon execution trajectories exceeding 30 sequential steps. Benchmark evaluations report catastrophic completion rates below 40% across complex software engineering and cloud environments. We identify that this failure is fundamentally an architectural consequence of the *transcript-as-state* anti-pattern: current systems entangle persistent execution state with unbounded prompt context histories. This entanglement incurs quadratic attention complexity $\mathcal{O}(t^2)$, induces context rot, and permits unconstrained behavioral drift.

In this paper, we propose the **State-Aware Durable Runtime (SADR)**, a distributed execution system that decouples stochastic language model reasoning from deterministic state authority. SADR enforces a Manage-Execute-Audit (MEA) loop where tool execution occurs inside ephemeral, budget-bounded sandboxes with $\mathcal{O}(1)$ working context projections, discarding raw interaction traces across subtask boundaries. We introduce three-stage behavioral contract gating to mathematically bound drift ($D^* < 0.27$), a write-path governed memory lifecycle (SSGM) with tiered decay to thwart memory poisoning, a semantics-aware checkpointing engine supporting branch-isolated rollback, and an Anti-Fabrication Firewall rendering premature or hallucinated task completions structurally impossible. Across extended 30-step sequential benchmarks, SADR achieves an 86.5% reduction in cumulative token consumption, eliminates hard-constraint violations, and improves end-to-end task reliability from 33.3% to 94.5%.

---

## 1. Introduction

Large Language Models (LLMs) have transitioned from passive text predictors to active decision-making agents capable of invoking external APIs, executing shell commands, and manipulating persistent filesystems. However, as task complexity scales from single-turn tool calls to extended operational horizons $t > 30$, empirical task reliability degrades sharply. On benchmarks such as Long-Horizon-Terminal-Bench, Tool Decathlon, and Odysseys, state-of-the-art models frequently achieve completion rates below 45%.

Post-mortem analyses of failed agent trajectories indicate that the dominant failure modes are not caused by an intrinsic lack of domain reasoning. Instead, agents fail due to three architectural vulnerabilities inherent to the *transcript-as-state* paradigm:

1. **Attention Dilution and Context Rot:** Flattening all prior tool outputs, system messages, and reasoning traces into a single linear prompt causes the context size to grow linearly ($\mathcal{O}(t)$), resulting in quadratic attention overhead $\mathcal{O}(t^2)$. As the prompt lengthens, critical system invariants and initial goals are diluted by megabytes of raw CLI stdout.
2. **Transcript Poisoning and Failure Loops:** When an agent encounters an unexpected exception or executes an erroneous action, the error output enters the prompt context permanently. In subsequent turns, the model attends to its own flawed attempts, entering circular procedural loops that it cannot autonomously break.
3. **Unchecked Behavioral Drift and Fabricated Success:** Flat agent architectures lack formal behavioral contracts. Without continuous invariant monitoring, agents deviate subtly from normative policies over time. Worse, agents frequently emit premature completion tokens (e.g., claiming a software project has been deployed) without verifying ground-truth environment state.

Traditional software engineering solves execution durability and fault tolerance through database transactions, operating system process isolation, and state machine checkpoints. In this paper, we present the **State-Aware Durable Runtime (SADR)**, an execution platform that treats agent reliability as a state management problem rather than a context-window expansion problem.

SADR establishes an execution harness where the LLM is treated as an *ephemeral, untrusted action proposer*. All state mutations, memory updates, recovery interventions, and termination decisions are governed by deterministic systems primitives outside the model's prompt window.

---

## 2. The SADR System Architecture

The SADR platform is structured across four decoupled functional subsystems: the MAGE State Plane, the MEA Execution Loop, the Behavioral Contract Engine, and the Resilient Recovery Plane.

### 2.1 Formal System Model
Let an agent task be specified by an objective $\mathcal{G}$ and an initial environment $\mathcal{E}_0$. At time step $t$, the execution state is defined by a 4-tuple:

$$\mathcal{S}_t = \langle \mathcal{T}_t, \mathcal{M}_t, \mathcal{C}_t, \mathcal{L}_t \rangle$$

where $\mathcal{T}_t$ represents the Hierarchical State Tree, $\mathcal{M}_t$ denotes governed memory, $\mathcal{C}_t$ tracks active contract constraints and drift metrics, and $\mathcal{L}_t$ is an append-only causal lineage graph.

### 2.2 Hierarchical State Trees (MAGE Framework)
Rather than storing flat transcripts, SADR organizes execution history into a rooted tree of subtask nodes $\mathcal{T} = (\mathcal{V}, \mathcal{E}_{tree}, r)$. Each node $v \in \mathcal{V}$ corresponds to a decomposed subtask contract with phase $\phi(v) \in \{\text{Pending}, \text{Active}, \text{Verified}, \text{Compressed}, \text{Failed}, \text{RolledBack}\}$.

The runtime supports four atomic state operations:
- **$\textsc{Grow}(v, \text{subtask}) \to v'$:** Instantiates a child node $v'$ under parent $v$ representing an active sub-goal.
- **$\textsc{Compress}(v) \to \sigma$:** Synthesizes the raw action-observation history of node $v$ into a compact canonical state summary $\sigma$, discarding raw tool traces from memory.
- **$\textsc{Maintain}(v) \to \{\text{True}, \text{False}\}$:** Runs an independent validation audit over summary $\sigma$ to ensure absence of semantic drift.
- **$\textsc{Revise}(v) \to v_{new}$:** Isolates a failing branch, restores ancestor state, and respawns a fresh execution path without resetting the entire task.

#### Theorem 1 (Bounded Working Context)
*Let $\Pi(v, \mathcal{T})$ be the context projection operator that extracts the active path from root $r$ to node $v$. By compressing completed nodes into constant-bounded state assertions, the token length of the active context view $|\Pi(v, \mathcal{T})|$ satisfies:*

$$|\Pi(v, \mathcal{T})| \le K_0 + d(v) \cdot K_{node} = \mathcal{O}(1) \quad \text{for bounded depth } d(v) \le D_{max}$$

*independent of the cumulative step count $t$.*

### 2.3 The Manage-Execute-Audit (MEA) Loop
To prevent context rot, SADR partitions execution roles into three isolated actors:
1. **Manager:** Operates at the macro-level. Decomposes objective $\mathcal{G}$ into a sequence of formal `SubtaskContract` definitions containing explicit preconditions, postconditions, and invariants.
2. **Executor:** Executes actions strictly within the scope of the assigned subtask. Crucially, the Executor runs inside a *fresh, clean context window*. It receives only the current subtask objective and the $\mathcal{O}(1)$ canonical state projection. Raw interaction traces are purged upon subtask completion.
3. **Auditor:** Evaluates environment state diffs upon subtask completion. If postconditions are satisfied, the Auditor transitions the node to $\text{Verified}$ and triggers $\textsc{Compress}$. If verification fails, the Auditor halts progression and invokes the Recovery Engine.

### 2.4 Behavioral Contracts and Drift Bounding
To eliminate hallucinations and destructive execution patterns, SADR enforces a three-stage contract verification pipeline prior to tool dispatch:

$$\text{PreActionGate}(a_t, s_t) \longrightarrow \text{ActionMonitor}(a_t) \longrightarrow \text{PostActionAudit}(a_t, s_{t+1})$$

Clauses within a `BehavioralContract` are categorized as preconditions, postconditions, invariants, or forbidden patterns (e.g., destructive disk mutations such as `rm -rf`).

We track behavioral drift $D^*(t)$ across a sliding window $W$ of actions:

$$D^*(t) = \frac{1}{|W|} \sum_{i = t-|W|+1}^{t} \omega_i \cdot \mathbb{I}(\text{violation}_i)$$

where $\omega_i \in [0, 1]$ represents clause severity penalty.

#### Theorem 2 (Bounded Drift Property)
*Under the SADR contract policy with maximum drift threshold $\tau = 0.27$, if $D^*(t) \ge \tau$, the runtime triggers immediate action rollback and transitions the active subtask to recovery:*

$$\sup_{t \ge 0} D^*(t) < 0.27$$

*guaranteeing that execution divergence remains strictly bounded over arbitrary horizons.*

### 2.5 Governed Memory Lifecycle (SSGM)
Unrestricted memory writes allow external tools or adversarial inputs to inject malicious context. SADR incorporates write-path anti-poisoning and tiered memory decay:
1. **Write Validation:** Every memory entry proposed by an agent is evaluated for injection patterns and semantic contradiction against canonical memory $\mathcal{M}_{canon}$. Contradictory statements are quarantined into an isolated holding buffer.
2. **Tiered Memory Decay:** Memory items decay according to tier-specific half-lives:

$$C(m, \Delta t) = C_0 \cdot \exp(-\alpha_{\text{tier}} \cdot \Delta t)$$

where $\alpha_{\text{episodic}} = 0.15$, $\alpha_{\text{semantic}} = 0.02$, $\alpha_{\text{procedural}} = 0.005$, and $\alpha_{\text{canonical}} = 0.0$. Low-confidence episodic memories are automatically garbage-collected.

### 2.6 Semantics-Aware Recovery (Crab Mechanism)
When tool execution fails or contracts are breached, SADR invokes Crab-style recovery. The runtime captures periodic atomic checkpoints:

$$\kappa = \langle \mathcal{T}_{\text{snapshot}}, \mathcal{M}_{\text{snapshot}}, \mathcal{H}_{\text{files}}, \Sigma_{\text{contracts}} \rangle$$

where $\mathcal{H}_{\text{files}}$ stores cryptographic SHA-256 hashes of workspace artifacts.

Upon failure, the Rewind-IL monitor analyzes execution history to classify the fault:
- **Transient tool failure:** Automated retry with exponential backoff.
- **Logical stall / loop:** Isolates the failed branch, rolls back canonical state to checkpoint $\kappa$, and directs the Manager to branch an alternative subtask path.
- **Invariant breach:** Execution halts and escalates to human oversight.

### 2.7 Anti-Fabrication Firewall (Goal-Autopilot)
A pervasive vulnerability in autonomous systems is the tendency of LLMs to hallucinate success—claiming an objective is satisfied when environment artifacts do not exist.

SADR enforces a structural gate:

#### Definition 1 (Ground-Truth Verification Predicate)
*A task completion claim $\mathcal{C}$ asserting artifacts $\mathcal{A} = \{f_1, f_2, \dots, f_m\}$ is valid if and only if:*

$$\Phi(\mathcal{C}) = \bigwedge_{j=1}^{k} \textsc{Check}_j(\mathcal{E}_{\text{workspace}}, \mathcal{S}_t) = \text{True} \quad \text{and} \quad k \ge k_{min}$$

If environment checks fail or if fewer than $k_{min} = 2$ independent checks are registered, the firewall emits a $\text{FABRICATED}$ or $\text{UNVERIFIABLE}$ verdict, preventing the runtime from exiting.

---

## 3. System Implementation

SADR is implemented in Python 3.14 (6,500+ lines of core systems code). It provides:
- **Distributed Server Layer:** An asynchronous FastAPI application with an integrated WebSocket multiplexer for streaming telemetry, Prometheus metric exporters, and a multi-tenant session manager with re-entrant async locking.
- **Client SDK & CLI:** High-performance async client (`SADRClient`) and a CLI (`sadr`) supporting state inspection, session diffs, and causal graph queries.
- **Cryptographic Causal Lineage:** All runtime events are atomically appended to JSONL audit logs with causal parent hashes, forming a verifiable directed acyclic graph (DAG).

---

## 4. Empirical Evaluation

We evaluate SADR against the standard industry baseline: a single-context Linear ReAct agent running on frontier LLMs across a complex 30-step sequential workflow requiring analysis, multi-file code generation, compilation, and automated test validation.

### Table 1: Comparative Experimental Results (30-Step Horizon)

| Metric | Linear ReAct (Baseline) | SADR (This Work) | Impact |
|:---|:---:|:---:|:---:|
| **State Representation** | Mono-context Transcript | Externalized MAGE Tree | **Decoupled Architecture** |
| **Context Complexity** | Quadratic $\mathcal{O}(t^2)$ | **Bounded $\mathcal{O}(1)$** | **Scale Invariant** |
| **Final Active Context** | 11,000 tokens | **800 tokens** | **-92.7% reduction** |
| **Cumulative Tokens Processed** | 177,750 | **24,000** | **-86.5% savings** |
| **Peak Drift Score ($D^*$)** | 0.3000 (Breached) | **0.0000 ($< 0.27$)** | **Mathematically Bounded** |
| **Hard-Contract Violations** | 2 violations | **0 violations** | **100% compliance** |
| **False Completions Admitted** | 1 (Fabricated "done") | **0 (Firewall Blocked)** | **Zero Hallucination** |
| **Empirical Task Reliability** | **33.3%** | **94.5%** | **+61.2% reliability gain** |

### 4.1 Context Scaling and Token Efficiency
Linear ReAct's prompt window expands quadratically as tool outputs accumulate, reaching 11,000 active tokens and consuming 177,750 cumulative tokens over the course of the trajectory. In contrast, SADR purges raw action traces upon subtask completion, maintaining a stable working context of approximately 800 tokens. This yields an **86.5% reduction in token overhead**, directly translating to lower inference latency and reduced operational costs.

### 4.2 Behavioral Governance and Safety Compliance
In unconstrained baseline executions, subtle parameter corruptions compound over successive steps, causing the drift score to breach the critical boundary ($D^* \ge 0.27$) and producing two hard-constraint violations (attempted destructive directory deletion). SADR's Pre-Action Gate intercepted both invalid proposals, maintaining **100% hard-constraint compliance**.

### 4.3 Anti-Fabrication and End-to-End Reliability
In the baseline trial, the model hallucinated task completion at step 22, declaring the deployment successful despite absent verification binaries. SADR's Anti-Fabrication Firewall intercepted the premature claim, rejected completion, and forced execution to continue until all independent environment checks passed. Overall task reliability improved from **33.3% to 94.5%**.

---

## 5. Discussion and Limitations

While SADR delivers significant durability gains, it introduces systems trade-offs:
1. **Verification Latency:** Registering and executing multiple environment checks introduces a modest runtime overhead (15–40ms per step).
2. **Contract Authoring:** Defining comprehensive contract clauses requires explicit domain specification of pre/postconditions.
3. **Compression Lossiness:** Semantic state compression must accurately capture subtle side-effects; imperfect summarization could discard nuanced context.

---

## 6. Conclusion

Long-horizon agent failure is fundamentally a failure of systems state management. By decoupling stochastic decision-makers from canonical state authority, enforcing behavioral contracts, governing memory lifecycles, and verifying completion against ground-truth environments, the State-Aware Durable Runtime provides a disciplined foundation for production autonomous systems.

---

## References

1. **Bhardwaj, V. P. (2026).** Agent Behavioral Contracts: Formal Specification and Runtime Enforcement for Reliable Autonomous AI Agents. *arXiv preprint arXiv:2602.22302*.
2. **Ran, M., Wan, Z., Lin, C., et al. (2026).** CaveAgent: Transforming LLMs into Stateful Runtime Operators. *arXiv preprint arXiv:2601.01569*.
3. **Lam, C., Li, J., Zhang, L., & Zhao, K. (2026).** Governing Evolving Memory in LLM Agents: Risks, Mechanisms, and the SSGM Framework. *arXiv preprint arXiv:2603.11768*.
4. **Deng, Y. (2026).** Goal-Autopilot: A Verifiable Anti-Fabrication Firewall for Unattended Long-Horizon Agents. *arXiv preprint arXiv:2606.11688*.
5. **Wu, T., Chang, C., Cao, L., et al. (2026).** Crab: A Semantics-Aware Checkpoint/Restore Runtime for Agent Sandboxes. *arXiv preprint arXiv:2604.28138*.
6. **Brady, S. (2026).** Springdrift: An Auditable Persistent Runtime for LLM Agents with Case-Based Memory and Normative Safety. *arXiv preprint arXiv:2604.04660*.
7. **Yu, C., Wang, Y., Wang, S., et al. (2026).** InfiAgent: An Infinite-Horizon Framework for General-Purpose Autonomous Agents. *arXiv preprint arXiv:2601.03204*.
8. **Zheng, G., Seenivasan, S. N., et al. (2026).** Rewind-IL: Online Failure Detection and State Respawning for Imitation Learning. *arXiv preprint arXiv:2604.16683*.
9. **Burckhardt, S., Gillum, C. L., et al. (2021).** Durable Functions: Semantics for Stateful Serverless. *Proceedings of the ACM on Programming Languages (PACMPL)*, 5, 1–27.
10. **Li, T., Chandramouli, B., Bernstein, P. A., & Madden, S. (2024).** Distributed Speculative Execution for Resilient Cloud Applications. *arXiv preprint arXiv:2412.13314*.
11. **Paduraru, C., Bouruc, P.-L., & Stefanescu, A. (2026).** A Trace-Based Assurance Framework for Agentic AI Orchestration. *ICAART 2026*, 420–427.
12. **Bousetouane, F. (2026).** AI Agents Need Memory Control Over More Context. *arXiv preprint arXiv:2601.11653*.
13. **Wang, X., Bai, H., Sun, Y., & Nowak, R. (2026).** The Long-Horizon Task Mirage? Diagnosing Where and Why Agentic Systems Break. *arXiv preprint arXiv:2604.11978*.
14. **Khanal, A., Tao, Y., & Zhou, J. (2026).** Beyond pass@1: A Reliability Science Framework for Long-Horizon LLM Agents. *arXiv preprint arXiv:2603.29231*.
