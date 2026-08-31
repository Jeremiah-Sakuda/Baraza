"""The doctrine compiler — fold state → the session's operating policy.

A **doctrine** is the set of rules the agent works under, folded from the
committed record and nothing else: not a cache, not session memory, not a model
call. If a rule is in force, a committed claim with a verbatim quote and a turn
anchor put it there, and the rule carries that provenance all the way into the
rendered system prompt. Same doctrine, every rule cited.

Three properties are this module's whole purpose, each preventing a named
failure mode:

**Purity.** Compilation makes no model calls and reads no clocks. The imperative
wording of a rule is authored at extraction time (it rides in
``claim.extra["rule_text"]``); a claim without it gets a mechanical rendering
from its own fields. A compiler that asked a model to phrase the rules would
make the policy layer as unreplayable as the behavior it governs — the doctrine
would stop being evidence.

**Byte-stability.** Compiling the same event log yields a byte-identical
doctrine regardless of event arrival order or how the log's instants were
spelled when serialized. Fold → doctrine compilation is deterministic — the
claim stops there: the doctrine is reproducible; what a model does under it is
a separately measured question, never asserted. The property is enforced by
``tests/property/test_doctrine_stability.py``, and it is why nothing here
carries a compile-time wall-clock stamp: "when" is a property of the log, not
of the compilation.

**Refusal to pick.** When two committed rules collide — both ratified, neither
retracted — the compiler emits a :class:`ConflictNotice` carrying both sides
and puts *neither* rule in force. A compiler that silently chose the newer, the
louder, or the more convenient side would be the approver with a model: it
would resolve a dispute the user never adjudicated. The notice is the honest
output; adjudication happens in the approval flow, on the record.

The visibility boundary applies here exactly as it does in the reconciler: an
unreadable committed belief is **counted** (it can suspend a readable rule it
collides with, and it increments ``withheld``) but its text is never rendered —
every quote in a rule or a notice comes through ``claim.quote_for(audience)``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from baraza.fold.graph import GraphState
from baraza.schema.claim import Claim, Provenance
from baraza.schema.temporal import EpochMillis, intervals_overlap
from baraza.schema.visibility import Audience, readable_by

__all__ = [
    "BELIEF_HINTS",
    "DoctrineRule",
    "ConflictSide",
    "ConflictNotice",
    "Doctrine",
    "compile",
    "render_system_prompt",
]


BELIEF_HINTS: frozenset[str] = frozenset(
    {
        "preference",
        "rule",
        "policy",
        "judgment",
        "working style",
        "estimation policy",
        "citation policy",
        "visibility policy",
        "routing",
        "threshold",
        "exception",
    }
)
"""The belief boundary, second half.

A claim is **belief-shaped** — eligible to become doctrine — iff its provenance
is ``INTERVIEW`` (the user said it to the agent, quote and turn anchor
attached) **or** its normalized ``predicate_hint`` is in this set. The set
exists for corpus-provenance claims mined from the user's own prior artifacts:
a chat export can contain "never pad estimates" just as an interview turn can,
and the hint is how extraction marks it as a statement *about how to work*
rather than a fact about the world.

Matching is exact on the lowercased, stripped hint — deliberately not
substring matching, because a boundary you can wander across by phrasing
("signing authority" containing "authority") is not a boundary. A fact-shaped
claim (``signing authority``, ``dues``) never compiles into doctrine no matter
who committed it: the doctrine governs conduct, and promoting facts into rules
would let a ledger entry about the world silently become an instruction.
"""


def _is_belief_shaped(claim: Claim) -> bool:
    if claim.provenance is Provenance.INTERVIEW:
        return True
    return claim.predicate_hint.strip().lower() in BELIEF_HINTS


def _content_key(claim: Claim) -> str:
    """What a rule *says*, audience-independent, for conflict counting only.

    Uses the extraction-authored wording when present, else the structural
    fields. Reads ``object_literal`` directly rather than through the audience
    gate because this key is never rendered — it exists so an unreadable
    committed belief can still *count* toward a collision (the reconciler's
    count-but-never-quote rule, applied to compilation).
    """
    wording = claim.extra.get("rule_text") if isinstance(claim.extra, dict) else None
    if isinstance(wording, str) and wording.strip():
        base = wording
    else:
        base = f"{claim.predicate}|{claim.object_literal or claim.object_id or ''}"
    return " ".join(base.split()).lower()


# --------------------------------------------------------------------- output


@dataclass(frozen=True, slots=True)
class DoctrineRule:
    """One rule in force, with the provenance that justifies it.

    ``learned_at`` is the instant the belief was *stated* (the claim's
    ``observed_at``), not the instant it was ratified: the quote and the anchor
    point at the utterance, and a rule dated to its approval would detach the
    date from the evidence. The ratification instant lives in the log's
    ``claim.committed`` event, where an auditor can find it.
    """

    rule: str
    """Imperative text, usable directly in a system prompt."""

    claim_id: str
    quote: str
    anchor: str
    """The claim's locator — ``turn:t-9`` for interview testimony."""

    source_id: str
    learned_at: EpochMillis
    subject_id: str
    predicate_hint: str

    def annotation(self) -> str:
        """The provenance tag every rendered rule carries."""
        return f"[{self.claim_id} | {self.anchor}]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "claim_id": self.claim_id,
            "quote": self.quote,
            "anchor": self.anchor,
            "source_id": self.source_id,
            "learned_at": self.learned_at,
            "subject_id": self.subject_id,
            "predicate_hint": self.predicate_hint,
        }


@dataclass(frozen=True, slots=True)
class ConflictSide:
    """One side of an unadjudicated collision.

    ``quote`` is ``None`` when the compiling audience may not read that side —
    the collision is reported, the text is not.
    """

    claim_id: str
    quote: str | None
    anchor: str
    learned_at: EpochMillis

    def render(self) -> str:
        if self.quote is None:
            return (
                f"[{self.claim_id} | {self.anchor}] "
                "(a committed record not readable by this audience; "
                "counted, not quoted)"
            )
        return f'[{self.claim_id} | {self.anchor}] "{self.quote}"'


@dataclass(frozen=True, slots=True)
class ConflictNotice:
    """Two or more committed rules collide; none of them is in force.

    ``origin`` says how the collision was found: ``"structural"`` (same subject
    and hint, different content, overlapping validity) or ``"ledger"`` (an open
    contradiction the reconciler already adjudicated). Both routes exist
    because each catches what the other cannot: the ledger holds
    model-adjudicated collisions across differently-hinted claims; the
    structural check holds even before the reconciler has run.
    """

    subject_id: str
    predicate_hint: str
    sides: tuple[ConflictSide, ...]
    origin: str
    rationale: str = ""

    @property
    def claim_ids(self) -> tuple[str, ...]:
        return tuple(side.claim_id for side in self.sides)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "predicate_hint": self.predicate_hint,
            "origin": self.origin,
            "rationale": self.rationale,
            "sides": [
                {
                    "claim_id": s.claim_id,
                    "quote": s.quote,
                    "anchor": s.anchor,
                    "learned_at": s.learned_at,
                }
                for s in self.sides
            ],
        }


@dataclass(frozen=True, slots=True)
class Doctrine:
    """The compiled operating policy for one audience.

    Immutable, clockless, and content-addressed via :meth:`fingerprint` —
    two compiles of the same log are the same doctrine, byte for byte.
    """

    audience: Audience
    rules: tuple[DoctrineRule, ...]
    conflicts: tuple[ConflictNotice, ...]
    withheld: int
    """Committed belief-shaped claims this audience may not read and that are
    not already reported through a conflict notice. A count and never content —
    the same honesty the librarian's withheld count carries."""

    def rule_for(self, claim_id: str) -> DoctrineRule | None:
        for rule in self.rules:
            if rule.claim_id == claim_id:
                return rule
        return None

    def fingerprint(self) -> str:
        """Stable content hash; the doctrine-determinism replay compares this.

        Hashes claim IDs, rule text, anchors, and instants — not quotes.
        Claim IDs are already content-addressed over their quotes, so the
        quote's identity is in the hash without its text ever entering a
        digest body that could be logged.
        """
        body = {
            "audience": self.audience.value,
            "rules": [
                {
                    "claim_id": r.claim_id,
                    "rule": r.rule,
                    "anchor": r.anchor,
                    "source_id": r.source_id,
                    "learned_at": r.learned_at,
                }
                for r in self.rules
            ],
            "conflicts": [
                {
                    "subject_id": n.subject_id,
                    "predicate_hint": n.predicate_hint,
                    "origin": n.origin,
                    "claim_ids": sorted(n.claim_ids),
                }
                for n in self.conflicts
            ],
            "withheld": self.withheld,
        }
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """JSON shape for the web face's doctrine view."""
        return {
            "audience": self.audience.value,
            "fingerprint": self.fingerprint(),
            "rules": [r.to_dict() for r in self.rules],
            "conflicts": [n.to_dict() for n in self.conflicts],
            "withheld": self.withheld,
        }


# ------------------------------------------------------------------- compile


def compile(state: GraphState, *, audience: Audience) -> Doctrine:  # noqa: A001
    """Fold state → doctrine. Pure; total; refuses to adjudicate.

    Inclusion is three gates, in order: **committed** (the user ratified it),
    **belief-shaped** (see :data:`BELIEF_HINTS`), **readable by** ``audience``
    (the only visibility predicate). A claim failing the third gate is counted
    in ``withheld`` and can still suspend a colliding readable rule; it is
    never quoted.
    """
    beliefs = [c for c in state.committed_claims() if _is_belief_shaped(c)]

    suspended, notices = _find_conflicts(state, beliefs, audience)

    # A suspended claim is reported through its conflict notice; counting it
    # again in ``withheld`` would inflate the count and report one absence as
    # two. So the withheld tally covers only claims that would otherwise have
    # become rules.
    readable: list[Claim] = []
    withheld = 0
    for claim in beliefs:
        if claim.claim_id in suspended:
            continue
        if readable_by(claim, audience):
            readable.append(claim)
        else:
            withheld += 1

    # Deduplicate agreeing restatements: the same rule said twice (same subject,
    # hint, and content, different anchors) is one rule, dated to its first
    # statement — a doctrine that repeated itself once per restatement would
    # grow without the policy changing, and the diff would report noise.
    kept: dict[tuple[str, str], Claim] = {}
    for claim in readable:
        key = (claim.blocking_key, _content_key(claim))
        incumbent = kept.get(key)
        if incumbent is None or (claim.observed_at, claim.claim_id) < (
            incumbent.observed_at,
            incumbent.claim_id,
        ):
            kept[key] = claim

    rules: list[DoctrineRule] = []
    for claim in kept.values():
        quote = claim.quote_for(audience)
        if quote is None:
            # Cannot happen for a claim that passed readable_by above, but a
            # boundary this load-bearing fails closed rather than trusting
            # that two predicates stay in sync forever.
            withheld += 1
            continue
        rules.append(
            DoctrineRule(
                rule=_rule_text(claim, audience),
                claim_id=claim.claim_id,
                quote=quote,
                anchor=claim.anchor.locator,
                source_id=claim.anchor.source_id,
                learned_at=claim.observed_at,
                subject_id=claim.subject_id,
                predicate_hint=claim.predicate_hint.strip().lower(),
            )
        )

    # Chronological by learning, claim ID as tiebreak: the order is meaningful
    # to a reader (the doctrine's own history) and total (byte-stability).
    rules.sort(key=lambda r: (r.learned_at, r.claim_id))

    return Doctrine(
        audience=audience,
        rules=tuple(rules),
        conflicts=tuple(notices),
        withheld=withheld,
    )


def _rule_text(claim: Claim, audience: Audience) -> str:
    """The imperative wording, or a mechanical fallback from the claim itself.

    Extraction authors the imperative form and stores it on the claim; the
    compiler never phrases anything, so a claim arriving without it reads
    plainly rather than fluently. Plain and true beats fluent and invented.
    """
    wording = claim.extra.get("rule_text") if isinstance(claim.extra, dict) else None
    if isinstance(wording, str) and wording.strip():
        return " ".join(wording.split())
    body = claim.object_for(audience) or claim.object_id or ""
    return f"{claim.predicate.replace('_', ' ')}: {body}"


def _find_conflicts(
    state: GraphState, beliefs: list[Claim], audience: Audience
) -> tuple[set[str], list[ConflictNotice]]:
    """Collisions among committed beliefs. Suspends every claim involved.

    Runs over *all* committed beliefs, readable or not — counting, never
    quoting — so a private committed rule cannot be silently outvoted by a
    readable one it contradicts.
    """
    suspended: set[str] = set()
    notices: list[ConflictNotice] = []
    seen_sets: set[frozenset[str]] = set()

    # Structural: same blocking key, different content, overlapping validity.
    groups: dict[str, list[Claim]] = {}
    for claim in beliefs:
        groups.setdefault(claim.blocking_key, []).append(claim)

    for _, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        involved: set[str] = set()
        ordered = sorted(members, key=lambda c: (c.observed_at, c.claim_id))
        for a, b in combinations(ordered, 2):
            if _content_key(a) == _content_key(b):
                continue  # agreement, handled by deduplication
            if not intervals_overlap(
                a.valid_from, a.valid_until, b.valid_from, b.valid_until
            ):
                continue  # different periods are history, not a dispute
            involved.update((a.claim_id, b.claim_id))
        if not involved:
            continue
        sides = [c for c in ordered if c.claim_id in involved]
        id_set = frozenset(involved)
        suspended.update(involved)
        if id_set not in seen_sets:
            seen_sets.add(id_set)
            notices.append(_notice(sides, audience, origin="structural"))

    # Ledger: open contradictions whose every side is a committed belief. The
    # reconciler already called these genuine; compiling either side would act
    # on a dispute the user has not yet adjudicated.
    by_id = {c.claim_id: c for c in beliefs}
    for contradiction in state.open_contradictions():
        sides = [by_id[cid] for cid in contradiction.claim_ids if cid in by_id]
        if len(sides) < 2 or len(sides) != len(contradiction.claim_ids):
            continue
        id_set = frozenset(c.claim_id for c in sides)
        suspended.update(id_set)
        if id_set in seen_sets:
            continue
        seen_sets.add(id_set)
        ordered = sorted(sides, key=lambda c: (c.observed_at, c.claim_id))
        notices.append(
            _notice(
                ordered,
                audience,
                origin="ledger",
                rationale=contradiction.rationale,
            )
        )

    notices.sort(key=lambda n: (n.subject_id, n.predicate_hint, n.claim_ids))
    return suspended, notices


def _notice(
    sides: list[Claim], audience: Audience, *, origin: str, rationale: str = ""
) -> ConflictNotice:
    first = sides[0]
    return ConflictNotice(
        subject_id=first.subject_id,
        predicate_hint=first.predicate_hint.strip().lower(),
        origin=origin,
        rationale=rationale,
        sides=tuple(
            ConflictSide(
                claim_id=c.claim_id,
                quote=c.quote_for(audience),
                anchor=c.anchor.locator,
                learned_at=c.observed_at,
            )
            for c in sides
        ),
    )


# -------------------------------------------------------------------- render


def render_system_prompt(doctrine: Doctrine) -> str:
    """The working prompt section. Every rule keeps its provenance tag.

    The ``[claim_id | anchor]`` annotation is the point: when a transcript is
    later audited, each instruction in the prompt names the committed claim
    that put it there, so "why did it behave that way" has a checkable answer
    at the policy layer — and only there. No line of model output is ever
    attributed to a rule by this system; compliance is measured, not asserted.
    """
    lines: list[str] = [
        "OPERATING DOCTRINE",
        "Compiled from the committed record. Every rule below was stated by "
        "the user, ratified by the user, and cited to the moment it was said.",
        "",
    ]

    if not doctrine.rules:
        lines.append(
            "No committed rules are in force. Work from the task alone and "
            "ask rather than assume a preference."
        )
    else:
        for index, rule in enumerate(doctrine.rules, start=1):
            lines.append(f"{index}. {rule.rule} {rule.annotation()}")
            lines.append(f'   stated as: "{rule.quote}"')

    if doctrine.conflicts:
        lines.append("")
        lines.append(
            "UNRESOLVED CONFLICTS — the user's own committed statements "
            "collide. No rule from either side is in force until the user "
            "adjudicates. Do not resolve these yourself; if one becomes "
            "relevant, present both sides and ask which governs."
        )
        for notice in doctrine.conflicts:
            lines.append(f"* {notice.subject_id} / {notice.predicate_hint}:")
            lines.extend(f"  - {side.render()}" for side in notice.sides)

    if doctrine.withheld:
        lines.append("")
        lines.append(
            f"({doctrine.withheld} committed belief(s) exist that this "
            "audience may not read; they are counted, not shown.)"
        )

    return "\n".join(lines)
