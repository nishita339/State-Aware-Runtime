"""
Generate publication-quality infographics and flowcharts (300 DPI)
for the State-Aware Durable Runtime (SADR) research paper.

TEXT VISIBILITY FOCUS:
- Large, bold typography (12pt-18pt scaled equivalent)
- High-contrast color palette (dark text on light background with thick borders)
- Generous padding and proper aspect ratios for IEEE single/double-column layouts
- Pure ASCII standard labels to avoid font glyph substitution warnings
"""

import os
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches

os.environ["MPLCONFIGDIR"] = str(Path(__file__).parent / ".mplconfig")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

OUTPUT_DIR = Path(__file__).parent

# Set global matplotlib font styling for crystal-clear readability
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
    "font.size": 12,
    "font.weight": "bold",
    "axes.edgecolor": "#1a202c",
    "axes.linewidth": 1.5,
})


def generate_architecture_infographic():
    """Double-column high-impact architecture diagram with ultra-clear large text."""
    fig, ax = plt.subplots(figsize=(14, 10.5), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    # Header
    ax.text(
        50, 96.5,
        "STATE-AWARE DURABLE RUNTIME (SADR): GOVERNED EXECUTION PLANE",
        ha="center", va="center", fontsize=17, fontweight="heavy", color="#0f172a"
    )
    ax.text(
        50, 93.2,
        "Architectural Decoupling: Ephemeral LLM Reasoning  <--->  Deterministic Canonical State Authority",
        ha="center", va="center", fontsize=12.5, fontweight="semibold", color="#334155"
    )

    layers = [
        (
            "LAYER 1: EPHEMERAL ACTION PROPOSER (STOCHASTIC MODEL)",
            "• Proposes action a_t ~ pi(s_t) | Budget-bounded fresh context | Strictly NO direct state mutation rights",
            "#eff6ff", "#1d4ed8", 82
        ),
        (
            "LAYER 2: THREE-STAGE BEHAVIORAL CONTRACT ENGINE",
            "• Pre-Action Gate (Preconditions) -> Action Monitor -> Post-Action Audit | Sliding Drift Bound: D*(t) < 0.27",
            "#f0fdf4", "#15803d", 69
        ),
        (
            "LAYER 3: MANAGE-EXECUTE-AUDIT (MEA) EXECUTION LOOP",
            "• Manager (Subtask Planner) -> Executor (Fresh Ephemeral Sandbox) -> Auditor (State Diff Verifier)",
            "#faf5ff", "#7e22ce", 56
        ),
        (
            "LAYER 4: MAGE HIERARCHICAL CANONICAL STATE PLANE",
            "• Grow -> Compress (Raw tool traces purged) -> Maintain -> Revise | Guaranteed O(1) Working Context",
            "#fffbeb", "#b45309", 43
        ),
        (
            "LAYER 5: GOVERNED MEMORY LIFECYCLE (SSGM FRAMEWORK)",
            "• Write-Path Anti-Poisoning Filter | Tiered Decay: Episodic (15%/turn), Semantic (2%), Canonical (0%)",
            "#f0fdfa", "#0f766e", 30
        ),
        (
            "LAYER 6: SEMANTICS-AWARE CHECKPOINT & RECOVERY (CRAB ENGINE)",
            "• Atomic Checkpoints (State Tree + SHA-256 Hashes) | Rewind-IL Loop Detector | Branch-Isolated Rollback",
            "#fef2f2", "#b91c1c", 17
        ),
        (
            "LAYER 7: ANTI-FABRICATION FIREWALL & CAUSAL LINEAGE DAG",
            "• Physical Environment Assertions (k >= 2 checks) | Blocks False 'Done' | Cryptographic JSONL Provenance",
            "#f8fafc", "#334155", 4
        ),
    ]

    for title, desc, bg, border, y in layers:
        rect = patches.FancyBboxPatch(
            (5, y - 4), 90, 8.8,
            boxstyle="round,pad=1.2,rounding_size=2.5",
            facecolor=bg, edgecolor=border, linewidth=2.8
        )
        ax.add_patch(rect)

        ax.text(
            8, y + 1.8, title,
            fontsize=13.5, fontweight="heavy", color=border, va="center"
        )
        ax.text(
            8, y - 1.8, desc,
            fontsize=11.5, fontweight="bold", color="#0f172a", va="center"
        )

        if y > 10:
            ax.annotate(
                "", xy=(50, y - 4.5), xytext=(50, y - 3.7),
                arrowprops=dict(arrowstyle="-|>", color="#475569", lw=2.5, mutation_scale=16)
            )

    plt.tight_layout()
    out_path = OUTPUT_DIR / "figure_architecture_infographic.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path}")


def generate_mea_flowchart():
    """Full-width high-contrast MEA flowchart with large, clearly visible labels."""
    fig, ax = plt.subplots(figsize=(13, 11), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(
        50, 96.5,
        "MEA EXECUTION LOOP & RECOVERY DECISION FLOWCHART",
        ha="center", va="center", fontsize=16, fontweight="heavy", color="#0f172a"
    )
    ax.text(
        50, 93.2,
        "Discrete Role Separation: Manager (Decompose) -> Executor (Fresh Context) -> Auditor (Verify Diff)",
        ha="center", va="center", fontsize=12, fontweight="semibold", color="#334155"
    )

    boxes = [
        ("1. TASK OBJECTIVE DECOMPOSITION\nManager creates Subtask Contracts (Pre/Postconditions)", 50, 84, "#eff6ff", "#1d4ed8", 74, 7),
        ("2. INITIALIZE FRESH CONTEXT SANDBOX\nOnly current subtask + O(1) Compressed Canonical State (No past traces)", 50, 72, "#faf5ff", "#7e22ce", 74, 7),
        ("3. ACTION PROPOSAL BY EXECUTOR\nStochastic model proposes tool call a_t ~ pi(s_t)", 50, 60, "#f0fdfa", "#0f766e", 74, 7),
        ("4. PRE-ACTION CONTRACT & DRIFT GATE\nIs action forbidden? Is sliding drift D*(t) < 0.27?", 50, 47, "#fffbeb", "#b45309", 64, 7.5),
        ("5. SANDBOX TOOL DISPATCH\nExecute action in isolation; capture state diff", 26, 33, "#f0fdf4", "#15803d", 42, 7),
        ("6. AUDITOR POSTCONDITION CHECK\nDoes environment state satisfy contract?", 26, 19, "#f1f5f9", "#334155", 42, 7),
        ("7. MAGE STATE COMPRESS & COMMIT\nPurge raw execution traces; commit clean diff", 26, 6, "#dcfce7", "#166534", 42, 7),
        ("RECOVERY ENGINE (REWIND-IL)\n• Invariant Breach -> Escalate\n• Drift D* >= 0.27 -> Rollback\n• Tool Error -> Retry / Branch", 76, 33, "#fef2f2", "#b91c1c", 42, 9),
        ("ANTI-FABRICATION FIREWALL\nEvaluate physical environment checks\n(k >= 2 independent assertions)", 76, 6, "#e0f2fe", "#0369a1", 42, 7),
    ]

    for text, x, y, bg, border, w, h in boxes:
        rect = patches.FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h,
            boxstyle="round,pad=1,rounding_size=2",
            facecolor=bg, edgecolor=border, linewidth=2.5
        )
        ax.add_patch(rect)
        ax.text(
            x, y, text,
            ha="center", va="center", fontsize=10.5, fontweight="heavy", color="#0f172a"
        )

    # Connections
    ax.annotate("", xy=(50, 76), xytext=(50, 80), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#334155"))
    ax.annotate("", xy=(50, 64), xytext=(50, 68), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#334155"))
    ax.annotate("", xy=(50, 51.5), xytext=(50, 56), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#334155"))

    # Approved branch
    ax.annotate("", xy=(26, 37), xytext=(38, 43), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#15803d"))
    ax.text(31, 41.5, "APPROVED [PASS]", fontsize=11, fontweight="heavy", color="#15803d", ha="right")

    # Blocked branch
    ax.annotate("", xy=(76, 38), xytext=(62, 43), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#b91c1c"))
    ax.text(70, 41.5, "BLOCKED / DRIFT [FAIL]", fontsize=11, fontweight="heavy", color="#b91c1c", ha="left")

    # Step 5 to 6
    ax.annotate("", xy=(26, 23), xytext=(26, 29), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#334155"))

    # Step 6 to 7 (Audit passed)
    ax.annotate("", xy=(26, 10), xytext=(26, 15), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#15803d"))
    ax.text(28, 12.5, "VERIFIED [PASS]", fontsize=10.5, fontweight="heavy", color="#15803d")

    # Step 6 to Recovery (Audit failed)
    ax.annotate("", xy=(55, 33), xytext=(47, 21), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#b91c1c"))
    ax.text(53, 25, "AUDIT FAILED [FAIL]", fontsize=10.5, fontweight="heavy", color="#b91c1c")

    # Step 7 to Firewall (Claim done)
    ax.annotate("", xy=(54, 6), xytext=(48, 6), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#0369a1"))
    ax.text(51, 8.5, "CLAIM 'DONE'", fontsize=10.5, fontweight="heavy", color="#0369a1", ha="center")

    # Recovery Loop Back to Step 2
    ax.annotate(
        "", xy=(88, 72), xytext=(88, 38),
        arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#b91c1c", connectionstyle="arc3,rad=-0.3")
    )
    ax.text(93, 55, "ROLLBACK TO\nCHECKPOINT", fontsize=10, fontweight="heavy", color="#b91c1c", ha="center")

    plt.tight_layout()
    out_path = OUTPUT_DIR / "figure_mea_flowchart.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path}")


def generate_mage_tree_infographic():
    """MAGE State Tree and context projection visualization with prominent text."""
    fig, ax = plt.subplots(figsize=(13, 8), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(
        50, 96,
        "MAGE HIERARCHICAL STATE TREE & BOUNDED CONTEXT PROJECTION",
        ha="center", va="center", fontsize=16, fontweight="heavy", color="#0f172a"
    )
    ax.text(
        50, 92,
        "Theorem 1: Discarding Raw Traces at Every Verified Boundary Guarantees O(1) Working Context",
        ha="center", va="center", fontsize=12, fontweight="semibold", color="#334155"
    )

    nodes = [
        ("ROOT NODE: GLOBAL OBJECTIVE G\nCanonical Initial State | Checkpoint kappa_0", 50, 80, "#f8fafc", "#334155"),
        ("SUBTASK 1: REQUIREMENTS VERIFIED\nCompressed: 85 tokens | Raw Traces Purged", 25, 58, "#dcfce7", "#166534"),
        ("SUBTASK 2: IMPLEMENTATION VERIFIED\nCompressed: 92 tokens | Raw Traces Purged", 25, 36, "#dcfce7", "#166534"),
        ("SUBTASK 3: ACTIVE TEST VALIDATION\nFresh Sandbox Context | <= 800 Tokens Total", 25, 14, "#fef3c7", "#d97706"),
        ("FAILED BRANCH A (TOOL LOOP)\n[QUARANTINED & PRUNED]\nCorrupted State Reverted", 75, 58, "#fee2e2", "#dc2626"),
        ("REVISED BRANCH B (ALTERNATIVE)\n[SPAWNED VIA REVISE PRIMITIVE]\nClean State Restored", 75, 36, "#f3e8ff", "#9333ea"),
    ]

    for text, x, y, bg, border in nodes:
        rect = patches.FancyBboxPatch(
            (x - 22, y - 7), 44, 14,
            boxstyle="round,pad=1,rounding_size=2",
            facecolor=bg, edgecolor=border, linewidth=2.5
        )
        ax.add_patch(rect)
        ax.text(
            x, y, text,
            ha="center", va="center", fontsize=10.5, fontweight="heavy", color="#0f172a"
        )

    # Active path arrows
    ax.annotate("", xy=(25, 66), xytext=(45, 75), arrowprops=dict(arrowstyle="-|>", lw=2.8, color="#166534"))
    ax.annotate("", xy=(25, 44), xytext=(25, 50), arrowprops=dict(arrowstyle="-|>", lw=2.8, color="#166534"))
    ax.annotate("", xy=(25, 22), xytext=(25, 28), arrowprops=dict(arrowstyle="-|>", lw=2.8, color="#d97706"))

    # Revision arrows
    ax.annotate("", xy=(75, 66), xytext=(55, 75), arrowprops=dict(arrowstyle="-|>", lw=2.8, color="#dc2626", linestyle="--"))
    ax.annotate("", xy=(75, 44), xytext=(75, 50), arrowprops=dict(arrowstyle="-|>", lw=2.8, color="#9333ea"))

    # Callout boxes with clear text
    ax.text(
        2, 36,
        "ACTIVE CONTEXT PROJECTION:\nPi(v, T) = [Root -> S1 -> S2 -> S3]\nBounded to O(1) Context Window",
        fontsize=10.5, fontweight="heavy", color="#1d4ed8",
        bbox=dict(boxstyle="round,pad=0.8", facecolor="#eff6ff", edgecolor="#1d4ed8", lw=2)
    )

    ax.text(
        54, 14,
        "BRANCH ISOLATION:\nPrunes failed trajectory without\nresetting uncorrupted progress",
        fontsize=10.5, fontweight="heavy", color="#9333ea",
        bbox=dict(boxstyle="round,pad=0.8", facecolor="#faf5ff", edgecolor="#9333ea", lw=2)
    )

    plt.tight_layout()
    out_path = OUTPUT_DIR / "figure_mage_tree.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path}")


def generate_firewall_flowchart():
    """Anti-Fabrication Firewall ground-truth verification pipeline."""
    fig, ax = plt.subplots(figsize=(13, 7.5), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(
        50, 95.5,
        "ANTI-FABRICATION FIREWALL: GROUND-TRUTH VERIFICATION PIPELINE",
        ha="center", va="center", fontsize=15.5, fontweight="heavy", color="#0f172a"
    )

    steps = [
        ("AGENT COMPLETION CLAIM\n'Task Complete / Code Deployed'\n(Self-Reported Claim)", 17, 62, "#f8fafc", "#334155", 30, 14),
        ("PHYSICAL ENVIRONMENT PROBE MATRIX\n(Requires k >= 2 Independent Checks)\n• File Existence & Non-Zero Byte Size\n• SHA-256 Binary Checksum Match\n• Test Process Returncode == 0\n• Regex Output Verification", 52, 62, "#fffbeb", "#b45309", 36, 21),
        ("VERDICT: GENUINE [PASS]\nTermination Admitted\nStatus: SUCCESS", 87, 76, "#dcfce7", "#166534", 24, 13),
        ("VERDICT: FABRICATED [FAIL]\nClaim Rejected / Blocked\nSession Remains Active", 87, 46, "#fee2e2", "#b91c1c", 24, 15),
    ]

    for text, x, y, bg, border, w, h in steps:
        rect = patches.FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h,
            boxstyle="round,pad=1,rounding_size=2",
            facecolor=bg, edgecolor=border, linewidth=2.5
        )
        ax.add_patch(rect)
        ax.text(
            x, y, text,
            ha="center", va="center", fontsize=10.5, fontweight="heavy", color="#0f172a"
        )

    # Arrows
    ax.annotate("", xy=(33.5, 62), xytext=(32, 62), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#334155"))
    ax.annotate("", xy=(74.5, 74), xytext=(70.5, 69), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#166534"))
    ax.text(71, 74.5, "ALL CHECKS PASS [PASS]", fontsize=10.5, fontweight="heavy", color="#166534")

    ax.annotate("", xy=(74.5, 48), xytext=(70.5, 55), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#b91c1c"))
    ax.text(71, 50, "FAIL / < 2 CHECKS [FAIL]", fontsize=10.5, fontweight="heavy", color="#b91c1c")

    # Formula Box
    formula_text = r"$\Phi(\mathcal{C}) = \bigwedge_{j=1}^k \mathrm{Check}_j(\mathcal{E}_{\mathrm{workspace}}, \mathcal{S}_t) \quad \mathrm{with} \quad k \geq 2$"
    ax.text(
        50, 16, formula_text,
        fontsize=13, ha="center", va="center",
        bbox=dict(boxstyle="round,pad=1", facecolor="#eff6ff", edgecolor="#1d4ed8", lw=2)
    )
    ax.text(
        50, 5,
        "Theorem 3 Guarantee: Hallucinated completion probability P(Success | Unfulfilled) = 0.0%",
        fontsize=11.5, fontweight="heavy", color="#1e40af", ha="center", va="center"
    )

    plt.tight_layout()
    out_path = OUTPUT_DIR / "figure_firewall_flowchart.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path}")


if __name__ == "__main__":
    generate_architecture_infographic()
    generate_mea_flowchart()
    generate_mage_tree_infographic()
    generate_firewall_flowchart()
    print("All publication infographics generated with high-visibility text!")
