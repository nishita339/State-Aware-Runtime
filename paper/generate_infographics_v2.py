"""
generate_infographics_v2.py - Re-generates all 4 infographics with professional
IEEE single-column target dimensions (figsize 4.2 to 4.5 inches wide) and large,
high-contrast, crystal-clear typography (9pt-13pt at 1:1 scale).
"""

import os
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches

PAPER_DIR = Path(__file__).parent
os.environ["MPLCONFIGDIR"] = str(PAPER_DIR / ".mplconfig")
(PAPER_DIR / ".mplconfig").mkdir(parents=True, exist_ok=True)

# Set global matplotlib font styling for clean academic publication
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
    "font.size": 9.5,
    "font.weight": "bold",
    "axes.edgecolor": "#1a202c",
    "axes.linewidth": 1.2,
})


def generate_architecture_infographic():
    """
    7-Layer Architecture Diagram designed specifically for IEEE column width (4.2 in).
    Large text that stays 100% visible and readable in PDF.
    """
    fig, ax = plt.subplots(figsize=(4.5, 4.2), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    # Title Banner
    ax.text(50, 96.5, "SADR 7-LAYER GOVERNED ARCHITECTURE", ha="center", va="center",
            fontsize=9.8, fontweight="heavy", color="#002B49")

    layers = [
        ("Layer 7: MEA Orchestrator", "6-Phase Atomic Transition Loop & Gatekeeper", "#eff6ff", "#1d4ed8", 85.5),
        ("Layer 6: Anti-Fabrication Firewall", "3-Tier Syntactic, Env & Crypto Attestation", "#fef2f2", "#b91c1c", 72.5),
        ("Layer 5: Behavioral Contract Engine", "Pre/Post Gate & Sliding Drift D*(t) < 0.27", "#fffbeb", "#b45309", 59.5),
        ("Layer 4: MAGE State Tree", "Copy-on-Write Branching & O(1) Context", "#faf5ff", "#7e22ce", 46.5),
        ("Layer 3: State Store & Vector Index", "Persistent RocksDB / SQLite & HNSW RAG", "#f0fdfa", "#0f766e", 33.5),
        ("Layer 2: Durable Append-Only WAL", "fsync Durability, CRC32 Checksums & Replay", "#f0fdf4", "#15803d", 20.5),
        ("Layer 1: Physical Sandbox Isolation", "Docker / MicroVM Namespace & Detours I/O", "#f8fafc", "#334155", 7.5),
    ]

    for title, desc, bg, border, y in layers:
        rect = patches.FancyBboxPatch(
            (3, y - 5.0), 94, 10.0,
            boxstyle="round,pad=0.8,rounding_size=2.0",
            facecolor=bg, edgecolor=border, linewidth=1.8
        )
        ax.add_patch(rect)
        ax.text(6, y + 1.6, title, fontsize=8.8, fontweight="heavy", color=border, va="center")
        ax.text(6, y - 2.0, desc, fontsize=7.2, fontweight="bold", color="#1e293b", va="center")

        if y > 10:
            ax.annotate("", xy=(50, y - 5.5), xytext=(50, y - 4.6),
                        arrowprops=dict(arrowstyle="-|>", color="#475569", lw=1.6, mutation_scale=10))

    plt.tight_layout(pad=0.4)
    out_path = PAPER_DIR / "figure_architecture_infographic.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path} ({out_path.stat().st_size} bytes)")


def generate_mea_flowchart():
    """
    MEA Flowchart designed for IEEE column width (4.5 in).
    Clear flowchart logic with large readable decision nodes.
    """
    fig, ax = plt.subplots(figsize=(4.5, 4.4), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(50, 97.0, "MICRO-EXECUTION ARCHETYPE (MEA) CYCLE", ha="center", va="center",
            fontsize=9.8, fontweight="heavy", color="#002B49")

    # Flowchart Nodes
    nodes = [
        ("1. Observe State Snapshot S_t", 50, 88.0, "#eff6ff", "#1d4ed8", 84, 7.0),
        ("2. Synthesize Proposed Action a_t", 50, 76.0, "#faf5ff", "#7e22ce", 84, 7.0),
        ("3. Pre-Validate Contract Predicates", 50, 64.0, "#fffbeb", "#b45309", 84, 7.0),
        ("4. Speculative Sandbox Execution", 28, 48.0, "#f0fdf4", "#15803d", 48, 7.5),
        ("5. Post-Validate & Firewall Verify", 28, 32.0, "#f1f5f9", "#334155", 48, 7.5),
        ("6. Atomic Commit to WAL (S_t+1)", 28, 16.0, "#dcfce7", "#166534", 48, 7.5),
        ("RECOVERY ENGINE\nRollback to S_t\nQuarantine a_t", 78, 40.0, "#fef2f2", "#b91c1c", 36, 15.0),
        ("FIREWALL GROUND-CHECK\nk >= 2 Env Assertions", 50, 4.0, "#e0f2fe", "#0369a1", 84, 6.5),
    ]

    for text, x, y, bg, border, w, h in nodes:
        rect = patches.FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h,
            boxstyle="round,pad=0.8,rounding_size=2.0",
            facecolor=bg, edgecolor=border, linewidth=1.6
        )
        ax.add_patch(rect)
        ax.text(x, y, text, ha="center", va="center", fontsize=7.6, fontweight="heavy", color="#0f172a")

    # Connectors
    ax.annotate("", xy=(50, 80.0), xytext=(50, 84.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#334155"))
    ax.annotate("", xy=(50, 68.0), xytext=(50, 72.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#334155"))

    # Branch Pass -> Step 4
    ax.annotate("", xy=(28, 52.5), xytext=(42, 60.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#15803d"))
    ax.text(32, 57.5, "PASS", fontsize=7.2, fontweight="heavy", color="#15803d", ha="right")

    # Branch Fail -> Recovery
    ax.annotate("", xy=(70, 48.0), xytext=(58, 60.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#b91c1c"))
    ax.text(68, 57.5, "VIOLATION", fontsize=7.2, fontweight="heavy", color="#b91c1c", ha="left")

    # Step 4 to 5
    ax.annotate("", xy=(28, 36.5), xytext=(28, 44.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#334155"))

    # Step 5 to 6 (Pass)
    ax.annotate("", xy=(28, 20.5), xytext=(28, 28.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#15803d"))
    ax.text(32, 24.5, "VERIFIED", fontsize=7.2, fontweight="heavy", color="#15803d")

    # Step 5 to Recovery (Fail)
    ax.annotate("", xy=(60, 40.0), xytext=(52, 32.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#b91c1c"))

    # Recovery Loop Back to Step 1
    ax.annotate("", xy=(88, 88.0), xytext=(88, 48.0),
                arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#b91c1c", connectionstyle="arc3,rad=-0.3"))

    # Step 6 to Done Check
    ax.annotate("", xy=(50, 7.5), xytext=(38, 12.0), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#0369a1"))

    plt.tight_layout(pad=0.4)
    out_path = PAPER_DIR / "figure_mea_flowchart.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path} ({out_path.stat().st_size} bytes)")


def generate_mage_tree():
    """
    MAGE Tree Diagram designed for IEEE column width (4.5 in).
    Crisp state branching and context bounding visualization.
    """
    fig, ax = plt.subplots(figsize=(4.5, 3.4), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(50, 96.0, "MAGE HIERARCHICAL STATE TREE (CoW)", ha="center", va="center",
            fontsize=9.8, fontweight="heavy", color="#002B49")

    nodes = [
        ("Root: Global Goal G (State S_0)\nCommitted Ancestor Trunk", 50, 81.0, "#f8fafc", "#334155", 78, 12.0),
        ("Subtask 1: Verified (S_1)\nCompressed: 85 tokens", 26, 52.0, "#dcfce7", "#166534", 44, 11.0),
        ("Subtask 2: Active (S_2)\nFresh Context <= 800t", 26, 23.0, "#fef3c7", "#d97706", 44, 11.0),
        ("Branch A: Tool Loop\n[Pruned & Rolled Back]", 74, 52.0, "#fee2e2", "#dc2626", 44, 11.0),
        ("Branch B: Alternative\n[Spawned via Revise]", 74, 23.0, "#f3e8ff", "#9333ea", 44, 11.0),
    ]

    for text, x, y, bg, border, w, h in nodes:
        rect = patches.FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h,
            boxstyle="round,pad=0.8,rounding_size=2.0",
            facecolor=bg, edgecolor=border, linewidth=1.6
        )
        ax.add_patch(rect)
        ax.text(x, y, text, ha="center", va="center", fontsize=7.4, fontweight="heavy", color="#0f172a")

    # Connectors
    ax.annotate("", xy=(26, 58.0), xytext=(42, 74.0), arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#166534"))
    ax.annotate("", xy=(26, 29.0), xytext=(26, 46.0), arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#d97706"))
    ax.annotate("", xy=(74, 58.0), xytext=(58, 74.0), arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#dc2626", linestyle="--"))
    ax.annotate("", xy=(74, 29.0), xytext=(74, 46.0), arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#9333ea"))

    ax.text(26, 6.0, "Canonical Linear Path (O(1) Context)", ha="center", fontsize=7.2, fontweight="bold", color="#166534")
    ax.text(74, 6.0, "Isolated Speculative Branches", ha="center", fontsize=7.2, fontweight="bold", color="#dc2626")

    plt.tight_layout(pad=0.4)
    out_path = PAPER_DIR / "figure_mage_tree.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path} ({out_path.stat().st_size} bytes)")


def generate_firewall_flowchart():
    """
    Anti-Fabrication Security Firewall designed for IEEE column width (4.5 in).
    Clear 3-tier defense pipeline.
    """
    fig, ax = plt.subplots(figsize=(4.5, 3.2), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(50, 96.0, "3-TIER ANTI-FABRICATION SECURITY FIREWALL", ha="center", va="center",
            fontsize=9.8, fontweight="heavy", color="#002B49")

    tiers = [
        ("Tier 1: Syntactic & Schema Validation", "JSON-Schema AST Parsing | Type & Range Verification", "#eff6ff", "#1d4ed8", 78.0),
        ("Tier 2: Dynamic Environmental Grounding", "Filesystem Inode & Port Probing | Reality Grounding", "#f0fdfa", "#0f766e", 51.0),
        ("Tier 3: Cryptographic Tool Attestation", "HMAC-SHA256 Nonce Verification | Blocks Hallucinated I/O", "#fef2f2", "#b91c1c", 24.0),
    ]

    for title, desc, bg, border, y in tiers:
        rect = patches.FancyBboxPatch(
            (4, y - 8.0), 92, 16.0,
            boxstyle="round,pad=0.8,rounding_size=2.0",
            facecolor=bg, edgecolor=border, linewidth=1.6
        )
        ax.add_patch(rect)
        ax.text(8, y + 2.5, title, fontsize=8.6, fontweight="heavy", color=border, va="center")
        ax.text(8, y - 3.2, desc, fontsize=7.2, fontweight="bold", color="#1e293b", va="center")

        if y > 30:
            ax.annotate("", xy=(50, y - 8.5), xytext=(50, y - 7.5),
                        arrowprops=dict(arrowstyle="-|>", color="#475569", lw=1.6, mutation_scale=10))

    ax.text(50, 5.0, "Exit Guarantee: P(False Success | Not Phi(C)) = 0", ha="center",
            fontsize=7.6, fontweight="heavy", color="#002B49")

    plt.tight_layout(pad=0.4)
    out_path = PAPER_DIR / "figure_firewall_flowchart.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Generated: {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == '__main__':
    print("Generating IEEE column-calibrated infographics...")
    generate_architecture_infographic()
    generate_mea_flowchart()
    generate_mage_tree()
    generate_firewall_flowchart()
    print("All infographics generated successfully!")
