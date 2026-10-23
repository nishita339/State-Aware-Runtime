"""
Memory Lifecycle Governance for State-Aware Durable Runtime.

Governs the formation, evolution, retrieval, and selective decay of agent
memory across tiered stores, with write-path anti-poisoning validation.

Research Foundations:
    - SSGM Framework (Lam et al., 2026): Structured State-Graph Memory with
      tiered episodic/semantic/procedural stores and selective forgetting to
      maintain O(1) context reconstruction.
    - ACC — Adaptive Contextual Control (Bousetouane, 2026): Anti-poisoning
      write validation ensuring that adversarial or fabricated observations
      cannot silently corrupt the canonical memory layer.
    - VMG — Volatile Memory Governance (Lin et al., 2026): Confidence-weighted
      decay curves per tier, garbage collection, and capacity enforcement to
      prevent unbounded memory growth while retaining high-value knowledge.

Architecture:
    MemoryEntry → WriteValidator → MemoryGovernor → DecayManager
                                    ↕ (tick loop)
                              Quarantine ↔ Canonical
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from state_aware_runtime.config import (
    MemoryPolicy,
    MemoryTier,
    MemoryVerdict,
    generate_id,
)

__all__ = [
    "MemoryEntry",
    "WriteValidator",
    "DecayManager",
    "MemoryGovernor",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Poisoning-detection regex patterns (ACC, Bousetouane 2026)
# ---------------------------------------------------------------------------
_POISONING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.IGNORECASE),
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
    re.compile(r"override\s+(safety|policy|contract)", re.IGNORECASE),
    re.compile(r"disregard\s+(rules|constraints|guidelines)", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions", re.IGNORECASE),
    re.compile(r"forget\s+everything\s+(above|before)", re.IGNORECASE),
]


# ============================================================================
# MemoryEntry
# ============================================================================


@dataclass
class MemoryEntry:
    """A single memory item with full lifecycle metadata.

    Each memory belongs to exactly one ``MemoryTier`` and carries provenance
    back to the action and state-tree node that produced it.  Confidence
    decays over time according to tier-specific rates (VMG, Lin et al. 2026).
    Suspicious entries can be quarantined pending review (ACC, Bousetouane
    2026).

    Attributes:
        entry_id:           Unique identifier (auto-generated with ``mem_`` prefix).
        tier:               Classification tier controlling decay and capacity.
        content:            The actual memory content string.
        source_action_id:   ID of the action that produced this memory.
        source_node_id:     ID of the state-tree node this memory originated from.
        confidence:         Confidence score in [0, 1]; decays each tick.
        access_count:       Number of times this entry has been retrieved.
        last_accessed:      Timestamp of the most recent read access.
        created_at:         Timestamp when this entry was created.
        tags:               Free-form tags for categorical filtering.
        embedding:          Optional dense vector for similarity search.
        is_quarantined:     Whether the entry is held for manual review.
        quarantine_reason:  Human-readable reason for quarantine, if any.
    """

    entry_id: str = field(default_factory=lambda: generate_id("mem"))
    tier: MemoryTier = MemoryTier.EPISODIC
    content: str = ""
    source_action_id: str = ""
    source_node_id: str = ""
    confidence: float = 1.0
    access_count: int = 0
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = field(default_factory=list)
    embedding: Optional[list[float]] = None
    is_quarantined: bool = False
    quarantine_reason: Optional[str] = None

    # -- mutators ----------------------------------------------------------

    def decay(self, rate: float) -> None:
        """Apply multiplicative confidence decay.

        Confidence is reduced by ``rate`` (clamped to [0, 1]).  CANONICAL
        entries are never decayed automatically.

        Args:
            rate: Decay fraction in [0, 1].  A rate of 0.10 means the entry
                  retains 90 % of its confidence each tick.
        """
        if self.tier is MemoryTier.CANONICAL:
            return  # canonical entries are immutable w.r.t. decay
        clamped = max(0.0, min(rate, 1.0))
        self.confidence = max(0.0, self.confidence - clamped * self.confidence)
        logger.debug(
            "Decayed %s (tier=%s) by %.3f → confidence=%.4f",
            self.entry_id, self.tier.name, clamped, self.confidence,
        )

    def access(self) -> None:
        """Record a read access — increments counter and refreshes timestamp."""
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)
        logger.debug("Accessed %s (count=%d)", self.entry_id, self.access_count)

    def quarantine(self, reason: str) -> None:
        """Place entry under quarantine pending review.

        Args:
            reason: Human-readable description of why this entry is suspect.
        """
        self.is_quarantined = True
        self.quarantine_reason = reason
        logger.info("Quarantined %s: %s", self.entry_id, reason)

    def release(self) -> None:
        """Release entry from quarantine."""
        self.is_quarantined = False
        self.quarantine_reason = None
        logger.info("Released %s from quarantine", self.entry_id)

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON / checkpoint storage."""
        return {
            "entry_id": self.entry_id,
            "tier": self.tier.name,
            "content": self.content,
            "source_action_id": self.source_action_id,
            "source_node_id": self.source_node_id,
            "confidence": self.confidence,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat(),
            "created_at": self.created_at.isoformat(),
            "tags": list(self.tags),
            "embedding": self.embedding,
            "is_quarantined": self.is_quarantined,
            "quarantine_reason": self.quarantine_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """Reconstruct a ``MemoryEntry`` from a serialised dict.

        Args:
            data: Dict previously produced by :meth:`to_dict`.

        Returns:
            Restored ``MemoryEntry`` instance.
        """
        return cls(
            entry_id=data["entry_id"],
            tier=MemoryTier[data["tier"]],
            content=data["content"],
            source_action_id=data.get("source_action_id", ""),
            source_node_id=data.get("source_node_id", ""),
            confidence=data.get("confidence", 1.0),
            access_count=data.get("access_count", 0),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            tags=data.get("tags", []),
            embedding=data.get("embedding"),
            is_quarantined=data.get("is_quarantined", False),
            quarantine_reason=data.get("quarantine_reason"),
        )


# ============================================================================
# WriteValidator
# ============================================================================


class WriteValidator:
    """Validates proposed memory writes to prevent poisoning and corruption.

    Implements the ACC (Adaptive Contextual Control) write-path gate
    (Bousetouane, 2026).  Every memory write passes through this validator
    before being admitted to the store.  It checks for:

    1. **Contradictions** with CANONICAL-tier entries (ground truth).
    2. **Suspiciously high initial confidence** on non-canonical writes.
    3. **Duplicate or near-duplicate content** (via token-overlap similarity).
    4. **Injection / manipulation patterns** that indicate prompt-injection
       or adversarial poisoning attempts.

    Args:
        policy: The ``MemoryPolicy`` controlling thresholds and toggles.
    """

    def __init__(self, policy: MemoryPolicy) -> None:
        self._policy = policy

    # -- public API --------------------------------------------------------

    def validate(
        self,
        entry: MemoryEntry,
        existing_memories: list[MemoryEntry],
    ) -> tuple[MemoryVerdict, str]:
        """Run all anti-poisoning checks on a proposed memory write.

        Args:
            entry:             The new ``MemoryEntry`` to validate.
            existing_memories: Current memory store for cross-referencing.

        Returns:
            A ``(MemoryVerdict, reason)`` tuple.  ``reason`` is an empty
            string when the verdict is ``ACCEPT``.
        """
        if not self._policy.enable_write_validation:
            return MemoryVerdict.ACCEPT, ""

        # 1. Injection / poisoning patterns
        if self.detect_poisoning_patterns(entry.content):
            reason = "Content matches known injection/poisoning patterns"
            logger.warning("Write REJECTED for %s: %s", entry.entry_id, reason)
            return MemoryVerdict.REJECT, reason

        # 2. Suspiciously high confidence on non-canonical entry
        #    A confidence of exactly 1.0 is the natural default for new
        #    entries.  Values strictly *above* 1.0 indicate manipulation.
        if entry.tier is not MemoryTier.CANONICAL and entry.confidence > 1.0:
            reason = (
                f"Suspiciously high confidence ({entry.confidence:.3f}) "
                f"for non-canonical tier {entry.tier.name}"
            )
            logger.warning("Write QUARANTINED for %s: %s", entry.entry_id, reason)
            return MemoryVerdict.QUARANTINE, reason

        # 3. Contradiction with canonical entries
        contradiction = self.detect_contradiction(entry, existing_memories)
        if contradiction is not None:
            reason = (
                f"Contradicts canonical entry {contradiction.entry_id} "
                f"(similarity={self.compute_similarity(entry.content, contradiction.content):.3f})"
            )
            if self._policy.quarantine_on_conflict:
                logger.warning("Write QUARANTINED for %s: %s", entry.entry_id, reason)
                return MemoryVerdict.QUARANTINE, reason
            logger.warning("Write REJECTED for %s: %s", entry.entry_id, reason)
            return MemoryVerdict.REJECT, reason

        # 4. Near-duplicate detection
        for existing in existing_memories:
            sim = self.compute_similarity(entry.content, existing.content)
            if sim >= self._policy.poisoning_similarity_threshold:
                reason = (
                    f"Near-duplicate of {existing.entry_id} "
                    f"(similarity={sim:.3f} ≥ threshold "
                    f"{self._policy.poisoning_similarity_threshold:.2f})"
                )
                logger.info("Write QUARANTINED for %s: %s", entry.entry_id, reason)
                return MemoryVerdict.QUARANTINE, reason

        return MemoryVerdict.ACCEPT, ""

    def detect_contradiction(
        self,
        new_entry: MemoryEntry,
        existing: list[MemoryEntry],
    ) -> Optional[MemoryEntry]:
        """Detect if *new_entry* contradicts any CANONICAL memory.

        A contradiction is detected when the similarity between a new
        non-canonical entry and a canonical entry exceeds the poisoning
        threshold AND the entries share overlapping tags, suggesting they
        describe the same subject differently.

        Args:
            new_entry: Proposed memory entry.
            existing:  Current memory store.

        Returns:
            The first contradicting canonical ``MemoryEntry``, or ``None``.
        """
        if new_entry.tier is MemoryTier.CANONICAL:
            return None  # canonical-vs-canonical is a merge, not contradiction

        for mem in existing:
            if mem.tier is not MemoryTier.CANONICAL:
                continue
            sim = self.compute_similarity(new_entry.content, mem.content)
            # High similarity but different content → likely contradiction
            if sim >= self._policy.poisoning_similarity_threshold:
                # Check tag overlap for topical relevance
                if set(new_entry.tags) & set(mem.tags) or sim >= 0.95:
                    return mem
        return None

    def detect_poisoning_patterns(self, content: str) -> bool:
        """Check content for known injection / manipulation patterns.

        Scans against a curated set of regex patterns that are characteristic
        of prompt-injection and memory-poisoning attacks.

        Args:
            content: The memory content string to inspect.

        Returns:
            ``True`` if any poisoning pattern is detected.
        """
        for pattern in _POISONING_PATTERNS:
            if pattern.search(content):
                logger.debug("Poisoning pattern matched: %s", pattern.pattern)
                return True
        return False

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Compute a simple token-overlap (Jaccard) similarity score.

        Uses whitespace-tokenised, case-folded token sets.  This is a
        lightweight stand-in for embedding-based similarity; it requires
        no external model and is deterministic.

        Args:
            text_a: First text.
            text_b: Second text.

        Returns:
            Jaccard similarity in [0.0, 1.0].
        """
        tokens_a = set(text_a.lower().split())
        tokens_b = set(text_b.lower().split())
        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)


# ============================================================================
# DecayManager
# ============================================================================


class DecayManager:
    """Handles selective forgetting and capacity enforcement.

    Implements the VMG (Volatile Memory Governance) strategy (Lin et al.,
    2026) with per-tier decay rates.  CANONICAL entries are exempt from
    automatic decay.

    The lifecycle each tick is:
        1. ``apply_decay``       — reduce confidence on all non-canonical entries
        2. ``garbage_collect``   — remove entries below the confidence floor
        3. ``enforce_capacity``  — trim tiers that exceed their entry caps

    Args:
        policy: The ``MemoryPolicy`` containing decay rates and thresholds.
    """

    # Tier → policy-field mapping for decay rates
    _DECAY_RATE_MAP: dict[MemoryTier, str] = {
        MemoryTier.EPISODIC: "episodic_decay_rate",
        MemoryTier.SEMANTIC: "semantic_decay_rate",
        MemoryTier.PROCEDURAL: "procedural_decay_rate",
    }
    _CAPACITY_MAP: dict[MemoryTier, str] = {
        MemoryTier.EPISODIC: "max_episodic_entries",
        MemoryTier.SEMANTIC: "max_semantic_entries",
    }

    def __init__(self, policy: MemoryPolicy) -> None:
        self._policy = policy

    # -- public API --------------------------------------------------------

    def apply_decay(self, memories: list[MemoryEntry]) -> list[MemoryEntry]:
        """Apply tier-specific confidence decay to all non-canonical memories.

        Args:
            memories: The full memory list (mutated in-place AND returned).

        Returns:
            The same list, with confidence values updated.
        """
        if not self._policy.enable_decay:
            return memories

        for mem in memories:
            if self.should_decay(mem):
                rate_attr = self._DECAY_RATE_MAP.get(mem.tier)
                if rate_attr is not None:
                    rate = getattr(self._policy, rate_attr)
                    mem.decay(rate)
        return memories

    def garbage_collect(
        self, memories: list[MemoryEntry],
    ) -> tuple[list[MemoryEntry], list[MemoryEntry]]:
        """Remove entries whose confidence has fallen below the threshold.

        CANONICAL and quarantined entries are never garbage-collected.

        Args:
            memories: The full memory list.

        Returns:
            A ``(kept, removed)`` tuple of lists.
        """
        kept: list[MemoryEntry] = []
        removed: list[MemoryEntry] = []
        for mem in memories:
            if mem.tier is MemoryTier.CANONICAL or mem.is_quarantined:
                kept.append(mem)
            elif mem.confidence < self._policy.min_confidence_threshold:
                removed.append(mem)
                logger.info(
                    "GC removed %s (tier=%s, confidence=%.4f)",
                    mem.entry_id, mem.tier.name, mem.confidence,
                )
            else:
                kept.append(mem)
        return kept, removed

    def enforce_capacity(self, memories: list[MemoryEntry]) -> list[MemoryEntry]:
        """Enforce per-tier capacity limits, evicting lowest-importance first.

        Tiers without an explicit cap (PROCEDURAL, CANONICAL) are unbounded.

        Args:
            memories: The full memory list.

        Returns:
            The pruned memory list.
        """
        for tier, cap_attr in self._CAPACITY_MAP.items():
            cap = getattr(self._policy, cap_attr)
            tier_mems = [m for m in memories if m.tier is tier]
            if len(tier_mems) <= cap:
                continue
            # Sort ascending by importance so we can pop the least important
            tier_mems.sort(key=lambda m: self.calculate_importance(m))
            evict_count = len(tier_mems) - cap
            evicted_ids = {m.entry_id for m in tier_mems[:evict_count]}
            for eid in evicted_ids:
                logger.info("Capacity eviction: %s from tier %s", eid, tier.name)
            memories = [m for m in memories if m.entry_id not in evicted_ids]
        return memories

    def should_decay(self, entry: MemoryEntry) -> bool:
        """Determine whether an entry is eligible for decay.

        CANONICAL and quarantined entries are exempt.

        Args:
            entry: The memory entry to check.

        Returns:
            ``True`` if the entry should be decayed this tick.
        """
        if entry.tier is MemoryTier.CANONICAL:
            return False
        if entry.is_quarantined:
            return False
        return True

    def calculate_importance(self, entry: MemoryEntry) -> float:
        """Compute a heuristic importance score for capacity eviction.

        The score combines tier weight, current confidence, and access
        frequency so that frequently-accessed, high-confidence entries in
        more-persistent tiers are retained longest.

        Formula (VMG, Lin et al. 2026):
            importance = tier_weight × confidence × (1 + log₂(access_count + 1))

        Args:
            entry: The memory entry.

        Returns:
            Importance score (higher → more important).
        """
        import math

        tier_weights: dict[MemoryTier, float] = {
            MemoryTier.EPISODIC: 1.0,
            MemoryTier.SEMANTIC: 2.0,
            MemoryTier.PROCEDURAL: 4.0,
            MemoryTier.CANONICAL: 10.0,
        }
        weight = tier_weights.get(entry.tier, 1.0)
        access_boost = 1.0 + math.log2(entry.access_count + 1)
        return weight * entry.confidence * access_boost


# ============================================================================
# MemoryGovernor
# ============================================================================


class MemoryGovernor:
    """Full memory lifecycle orchestrator.

    Coordinates ``WriteValidator`` and ``DecayManager`` to provide a
    governed memory store with:

    * **Validated writes** — every ``write()`` passes the ACC anti-poisoning
      gate before admission.
    * **Tracked reads** — every ``read()`` updates access metadata used by
      the decay and eviction algorithms.
    * **Tick-based maintenance** — ``tick()`` applies decay, garbage-collects
      low-confidence entries, and enforces per-tier capacity caps.
    * **Checkpoint/restore** — ``to_checkpoint()`` / ``from_checkpoint()``
      produce serialisable snapshots for the recovery engine.

    References:
        SSGM (Lam et al., 2026), ACC (Bousetouane, 2026), VMG (Lin et al., 2026).

    Args:
        policy: The ``MemoryPolicy`` governing thresholds and behaviour.
    """

    def __init__(self, policy: MemoryPolicy) -> None:
        self._policy = policy
        self._validator = WriteValidator(policy)
        self._decay_manager = DecayManager(policy)
        self.memories: list[MemoryEntry] = []
        self._tick_count: int = 0
        self._total_writes: int = 0
        self._rejected_writes: int = 0
        self._quarantined_writes: int = 0
        logger.info("MemoryGovernor initialised (policy=%s)", policy)

    # -- writes ------------------------------------------------------------

    def write(self, entry: MemoryEntry) -> tuple[MemoryVerdict, str]:
        """Perform a validated memory write.

        The entry is run through the ``WriteValidator``; accepted entries are
        appended to the store, quarantined entries are marked accordingly,
        and rejected entries are discarded.

        Args:
            entry: The proposed ``MemoryEntry``.

        Returns:
            A ``(MemoryVerdict, reason)`` tuple.
        """
        self._total_writes += 1
        verdict, reason = self._validator.validate(entry, self.memories)

        if verdict is MemoryVerdict.ACCEPT:
            self.memories.append(entry)
            logger.info("Memory ACCEPTED: %s (tier=%s)", entry.entry_id, entry.tier.name)
        elif verdict is MemoryVerdict.QUARANTINE:
            entry.quarantine(reason)
            self.memories.append(entry)
            self._quarantined_writes += 1
            logger.warning("Memory QUARANTINED: %s — %s", entry.entry_id, reason)
        else:  # REJECT
            self._rejected_writes += 1
            logger.warning("Memory REJECTED: %s — %s", entry.entry_id, reason)

        return verdict, reason

    # -- reads -------------------------------------------------------------

    def read(
        self,
        query: str,
        tier: Optional[MemoryTier] = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Retrieve memories matching *query*, with access tracking.

        Matches are scored by token-overlap similarity to *query*.
        Quarantined entries are excluded from read results.

        Args:
            query: Free-text search query.
            tier:  Optional tier filter.
            limit: Maximum number of results.

        Returns:
            List of matching ``MemoryEntry`` objects, sorted by descending
            relevance.
        """
        candidates = [
            m for m in self.memories
            if not m.is_quarantined and (tier is None or m.tier is tier)
        ]
        scored: list[tuple[float, MemoryEntry]] = []
        for mem in candidates:
            sim = self._validator.compute_similarity(query, mem.content)
            # Blend similarity with confidence for ranking
            score = sim * 0.7 + mem.confidence * 0.3
            scored.append((score, mem))

        scored.sort(key=lambda t: t[0], reverse=True)
        results = [mem for _, mem in scored[:limit]]

        for mem in results:
            mem.access()

        logger.debug("read(query=%r, tier=%s) → %d results", query, tier, len(results))
        return results

    # -- tick / maintenance ------------------------------------------------

    def tick(self) -> None:
        """Run one maintenance tick: decay → GC → capacity enforcement.

        Should be called once per agent action step.
        """
        self._tick_count += 1
        logger.debug("MemoryGovernor tick #%d", self._tick_count)

        self._decay_manager.apply_decay(self.memories)
        kept, removed = self._decay_manager.garbage_collect(self.memories)
        self.memories = kept
        if removed:
            logger.info("GC removed %d entries at tick %d", len(removed), self._tick_count)
        self.memories = self._decay_manager.enforce_capacity(self.memories)

    # -- canonical state ---------------------------------------------------

    def get_canonical_state(self) -> dict[str, Any]:
        """Return all CANONICAL-tier memories as structured state.

        Returns:
            Dict keyed by ``entry_id`` with content, tags, and confidence.
        """
        return {
            mem.entry_id: {
                "content": mem.content,
                "tags": mem.tags,
                "confidence": mem.confidence,
                "source_action_id": mem.source_action_id,
            }
            for mem in self.memories
            if mem.tier is MemoryTier.CANONICAL
        }

    # -- quarantine management ---------------------------------------------

    def get_quarantined(self) -> list[MemoryEntry]:
        """Return all entries currently under quarantine."""
        return [m for m in self.memories if m.is_quarantined]

    def release_from_quarantine(self, entry_id: str) -> bool:
        """Release a quarantined entry by its ID.

        Args:
            entry_id: The entry to release.

        Returns:
            ``True`` if the entry was found and released.
        """
        for mem in self.memories:
            if mem.entry_id == entry_id and mem.is_quarantined:
                mem.release()
                logger.info("Released %s from quarantine", entry_id)
                return True
        logger.warning("Entry %s not found or not quarantined", entry_id)
        return False

    # -- promotion ---------------------------------------------------------

    def promote(self, entry_id: str, new_tier: MemoryTier) -> bool:
        """Promote a memory entry to a higher (more persistent) tier.

        Promotion resets confidence to 1.0 since the entry has been
        explicitly endorsed.

        Args:
            entry_id: The entry to promote.
            new_tier: Target tier (should be higher than current).

        Returns:
            ``True`` if the entry was found and promoted.
        """
        _TIER_ORDER = {
            MemoryTier.EPISODIC: 0,
            MemoryTier.SEMANTIC: 1,
            MemoryTier.PROCEDURAL: 2,
            MemoryTier.CANONICAL: 3,
        }
        for mem in self.memories:
            if mem.entry_id == entry_id:
                if _TIER_ORDER.get(new_tier, 0) <= _TIER_ORDER.get(mem.tier, 0):
                    logger.warning(
                        "Cannot promote %s from %s to %s (not an upgrade)",
                        entry_id, mem.tier.name, new_tier.name,
                    )
                    return False
                old_tier = mem.tier
                mem.tier = new_tier
                mem.confidence = 1.0
                logger.info(
                    "Promoted %s: %s → %s", entry_id, old_tier.name, new_tier.name,
                )
                return True
        logger.warning("Entry %s not found for promotion", entry_id)
        return False

    # -- statistics --------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return memory statistics broken down by tier.

        Returns:
            Dict with tier counts, quarantine info, and write stats.
        """
        tier_counts: dict[str, int] = Counter()
        quarantined = 0
        for mem in self.memories:
            tier_counts[mem.tier.name] += 1
            if mem.is_quarantined:
                quarantined += 1

        return {
            "total_entries": len(self.memories),
            "by_tier": dict(tier_counts),
            "quarantined": quarantined,
            "total_writes": self._total_writes,
            "rejected_writes": self._rejected_writes,
            "quarantined_writes": self._quarantined_writes,
            "ticks": self._tick_count,
        }

    # -- checkpoint / restore ----------------------------------------------

    def to_checkpoint(self) -> dict[str, Any]:
        """Produce a serialisable snapshot of the entire memory state.

        Returns:
            Dict suitable for JSON serialisation and later restoration
            via :meth:`from_checkpoint`.
        """
        return {
            "memories": [m.to_dict() for m in self.memories],
            "tick_count": self._tick_count,
            "total_writes": self._total_writes,
            "rejected_writes": self._rejected_writes,
            "quarantined_writes": self._quarantined_writes,
        }

    def from_checkpoint(self, data: dict[str, Any]) -> None:
        """Restore memory state from a serialised snapshot.

        This replaces the current memory store entirely.

        Args:
            data: Dict previously produced by :meth:`to_checkpoint`.
        """
        self.memories = [
            MemoryEntry.from_dict(md) for md in data.get("memories", [])
        ]
        self._tick_count = data.get("tick_count", 0)
        self._total_writes = data.get("total_writes", 0)
        self._rejected_writes = data.get("rejected_writes", 0)
        self._quarantined_writes = data.get("quarantined_writes", 0)
        logger.info(
            "MemoryGovernor restored from checkpoint (%d entries)", len(self.memories),
        )
