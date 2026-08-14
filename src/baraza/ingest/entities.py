"""Entity resolution — a canonical table and an alias pass. Deliberately not ML.

The non-goal is explicit and worth restating, because "add a real entity
matcher" is the most tempting scope creep in this system: there is **no** entity
matcher here. A student organization has on the order of a hundred distinct
entities across a decade — officers, roles, accounts, vendors, events. The
cardinality does not justify a model, and a learned matcher would be a component
whose failures are hard to explain to the person whose institutional memory is
at stake.

Instead:

* A **canonical entity table**, seeded from the corpus and extended as
  extraction runs.
* An **alias pass** that proposes ``sameAs`` links using cheap, inspectable
  rules plus one Gemini call for the genuinely ambiguous residue.
* **Human confirmation** for anything the rules did not settle. The proposals
  are written to a review file; unconfirmed proposals do not become edges.
* ``sameAs`` **edges only**. No destructive merges, ever. ``ent:treasurer`` and
  ``ent:the-treasurer`` both stay in the log, both stay in every claim that used
  them, and identity resolves at query time through the fold's alias map.

The last point is what makes the whole thing reversible. A wrong merge in a
mutable store is unrecoverable; a wrong ``sameAs`` edge is one superseding event
away from being undone.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from baraza.llm import LLMClient

__all__ = [
    "Entity",
    "EntityTable",
    "AliasProposal",
    "AliasPass",
    "EntityScorecard",
]

# Role words that must never be collapsed with each other, however similar their
# surface forms. "Treasurer" and "Assistant Treasurer" differ by one token and
# by the entire question of who could sign a cheque.
_DISTINGUISHING = re.compile(
    r"(?i)\b(assistant|deputy|vice|co|interim|acting|former|outgoing|incoming|"
    r"junior|senior|elect)\b"
)

_STOPWORDS = {"the", "a", "an", "our", "of", "for", "and"}


@dataclass(slots=True)
class Entity:
    """One canonical thing, with the surface forms observed for it."""

    entity_id: str
    canonical_name: str
    kind: str = "unknown"
    surface_forms: set[str] = field(default_factory=set)
    first_seen_source: str | None = None

    def normalized(self) -> str:
        return _normalize(self.canonical_name)


def _normalize(name: str) -> str:
    """Lowercase, strip stopwords and punctuation. Not a similarity function."""
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", name.lower())
        if token and token not in _STOPWORDS
    ]
    return " ".join(tokens)


@dataclass(frozen=True, slots=True)
class AliasProposal:
    """A proposed ``sameAs`` edge, and the reason for it."""

    alias_id: str
    canonical_id: str
    rule: str
    confidence: float
    needs_human: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "alias_id": self.alias_id,
            "canonical_id": self.canonical_id,
            "rule": self.rule,
            "confidence": self.confidence,
            "needs_human": self.needs_human,
            "confirmed": None,
        }


class EntityTable:
    """The canonical table."""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}

    def observe(
        self, entity_id: str, surface: str, *, source_id: str | None = None
    ) -> Entity:
        entity = self._entities.get(entity_id)
        if entity is None:
            entity = Entity(
                entity_id=entity_id,
                canonical_name=surface.strip(),
                first_seen_source=source_id,
            )
            self._entities[entity_id] = entity
        entity.surface_forms.add(surface.strip())
        return entity

    def get(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def all(self) -> list[Entity]:
        return sorted(self._entities.values(), key=lambda e: e.entity_id)

    def __len__(self) -> int:
        return len(self._entities)


class AliasPass:
    """Proposes ``sameAs`` edges. Never applies them without confirmation."""

    def __init__(self, client: LLMClient | None = None):
        self.client = client

    def propose(self, table: EntityTable) -> list[AliasProposal]:
        entities = table.all()
        proposals: list[AliasProposal] = []
        seen: set[tuple[str, str]] = set()

        for i, left in enumerate(entities):
            for right in entities[i + 1 :]:
                pair = tuple(sorted((left.entity_id, right.entity_id)))
                if pair in seen:
                    continue
                seen.add(pair)

                proposal = self._compare(left, right)
                if proposal is not None:
                    proposals.append(proposal)

        return proposals

    def _compare(self, left: Entity, right: Entity) -> AliasProposal | None:
        left_norm, right_norm = left.normalized(), right.normalized()
        if not left_norm or not right_norm:
            return None

        # Hard guard, checked before any similarity rule: if exactly one side
        # carries a distinguishing modifier, they are different entities no
        # matter how close the strings are. This is the rule that keeps
        # "Treasurer" and "Assistant Treasurer" apart.
        left_mods = set(m.lower() for m in _DISTINGUISHING.findall(left.canonical_name))
        right_mods = set(
            m.lower() for m in _DISTINGUISHING.findall(right.canonical_name)
        )
        if left_mods != right_mods:
            return None

        # Rule 1 — identical after normalization. Safe to auto-confirm.
        if left_norm == right_norm:
            alias, canonical = _order(left, right)
            return AliasProposal(
                alias_id=alias.entity_id,
                canonical_id=canonical.entity_id,
                rule="identical-after-normalization",
                confidence=1.0,
                needs_human=False,
            )

        # Rule 2 — one is a token-subset of the other ("treasurer" ⊂ "club
        # treasurer"). Plausible, but "spring budget" ⊂ "spring budget appeal"
        # is not the same thing, so a human confirms.
        left_tokens, right_tokens = set(left_norm.split()), set(right_norm.split())
        if left_tokens < right_tokens or right_tokens < left_tokens:
            alias, canonical = _order(left, right)
            return AliasProposal(
                alias_id=alias.entity_id,
                canonical_id=canonical.entity_id,
                rule="token-subset",
                confidence=0.6,
                needs_human=True,
            )

        # Rule 3 — shared surface form. Two ids that were both written down for
        # the same string somewhere are probably the same thing.
        if left.surface_forms & right.surface_forms:
            alias, canonical = _order(left, right)
            return AliasProposal(
                alias_id=alias.entity_id,
                canonical_id=canonical.entity_id,
                rule="shared-surface-form",
                confidence=0.7,
                needs_human=True,
            )

        return None

    def write_review_file(
        self, proposals: Sequence[AliasProposal], path: Path | str
    ) -> Path:
        """Write proposals for human confirmation.

        Auto-confirmed proposals are marked so; everything else waits. The file
        is the human gate, and an unedited file means no ambiguous edge is
        applied — which is the correct default, not a blocked pipeline.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "_note": (
                        "sameAs proposals. Set \"confirmed\": true to apply an "
                        "edge, false to reject it. Proposals left null are NOT "
                        "applied. Nothing here is destructive: an edge can be "
                        "undone by appending a superseding event."
                    ),
                    "proposals": [
                        {**p.to_dict(), "confirmed": True if not p.needs_human else None}
                        for p in proposals
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return target

    @staticmethod
    def read_confirmed(path: Path | str) -> list[tuple[str, str]]:
        """Load only the confirmed edges. Null stays unapplied."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return [
            (p["alias_id"], p["canonical_id"])
            for p in payload.get("proposals", [])
            if p.get("confirmed") is True
        ]


def _order(left: Entity, right: Entity) -> tuple[Entity, Entity]:
    """Pick which id becomes the alias.

    The longer canonical name wins as canonical — a fuller form is more likely
    to be the one a human would recognize. Ties break on entity_id so the choice
    is deterministic across runs.
    """
    if len(left.canonical_name) > len(right.canonical_name):
        return right, left
    if len(right.canonical_name) > len(left.canonical_name):
        return left, right
    return (left, right) if left.entity_id > right.entity_id else (right, left)


@dataclass(slots=True)
class EntityScorecard:
    """Precision and recall against a hand-labelled fixture.

    The substrate gate requires ≥83% **as a measured rate**, which means this
    scorecard has to be run and its output recorded — not asserted. The gold
    labels live in ``fixtures/entities-gold.json`` and were written by hand
    against the generated corpus.
    """

    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return None if denominator == 0 else round(self.true_positive / denominator, 4)

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return None if denominator == 0 else round(self.true_positive / denominator, 4)

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if not p or not r:
            return None
        return round(2 * p * r / (p + r), 4)

    def describe(self) -> str:
        def fmt(value: float | None) -> str:
            return "not yet measured" if value is None else f"{value:.1%}"

        return (
            f"entity scorecard: precision {fmt(self.precision)}, "
            f"recall {fmt(self.recall)}, f1 {fmt(self.f1)} "
            f"(tp={self.true_positive} fp={self.false_positive} "
            f"fn={self.false_negative})"
        )

    @staticmethod
    def score(
        proposed: Iterable[tuple[str, str]], gold: Iterable[tuple[str, str]]
    ) -> EntityScorecard:
        proposed_set = {tuple(sorted(p)) for p in proposed}
        gold_set = {tuple(sorted(g)) for g in gold}
        return EntityScorecard(
            true_positive=len(proposed_set & gold_set),
            false_positive=len(proposed_set - gold_set),
            false_negative=len(gold_set - proposed_set),
        )
