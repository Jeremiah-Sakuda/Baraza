"""Doctrine diff — which belief changed which rule, between two compiles.

This is a **doctrine diff, never an output diff**. Each entry names the causal
claim honestly, via the provenance the compiler already carries: a rule is in
the doctrine because exactly one committed claim put it there, so "this rule
appeared because of this claim" is a statement the data structure proves. What
the model then *did* under the old or new doctrine is a different artifact
(before/after output pairs on a fixed task) and no entry here ever attributes a
line of output to a rule — that causality is not measurable at this layer and
is not claimed.

The diff exists for two surfaces: the terminal (``render()`` lines) and the web
face's doctrine view (``to_dict()``). Both say the same things; neither says
more than the compiler knows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from baraza.doctrine.compiler import ConflictNotice, Doctrine, DoctrineRule

__all__ = [
    "RuleAdded",
    "RuleRemoved",
    "RuleChanged",
    "DoctrineDiff",
    "diff",
]


@dataclass(frozen=True, slots=True)
class RuleAdded:
    """A rule now in force that was not before. Cause: its own claim."""

    rule: DoctrineRule

    @property
    def causal_claim_id(self) -> str:
        return self.rule.claim_id

    def render(self) -> str:
        return f"+ {self.rule.rule} — belief {self.rule.claim_id} [{self.rule.anchor}]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "added",
            "causal_claim_id": self.causal_claim_id,
            "rule": self.rule.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RuleRemoved:
    """A rule no longer in force.

    ``note`` distinguishes the one removal cause a diff of two doctrines can
    prove — suspension by a conflict visible in the new doctrine — from the
    rest (retraction, visibility tightening), which look identical from here
    and are therefore reported together rather than guessed apart. The log
    holds the distinguishing event; the diff does not pretend to.
    """

    rule: DoctrineRule
    note: str

    @property
    def causal_claim_id(self) -> str:
        return self.rule.claim_id

    def render(self) -> str:
        return (
            f"- {self.rule.rule} — belief {self.rule.claim_id} "
            f"[{self.rule.anchor}] ({self.note})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "removed",
            "causal_claim_id": self.causal_claim_id,
            "note": self.note,
            "rule": self.rule.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RuleChanged:
    """The same subject and hint, now governed by a different claim.

    The causal claim is the **new** governing belief — the statement whose
    ratification changed the policy. The old claim is named so the pair is
    auditable, not because the diff knows why it left.
    """

    old: DoctrineRule
    new: DoctrineRule

    @property
    def causal_claim_id(self) -> str:
        return self.new.claim_id

    def render(self) -> str:
        return (
            f"~ {self.new.subject_id} / {self.new.predicate_hint} — "
            f'now "{self.new.rule}" per belief {self.new.claim_id} '
            f'[{self.new.anchor}]; was "{self.old.rule}" per {self.old.claim_id}'
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "changed",
            "causal_claim_id": self.causal_claim_id,
            "old": self.old.to_dict(),
            "new": self.new.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class DoctrineDiff:
    """Everything that changed between two doctrines, and nothing that didn't."""

    added: tuple[RuleAdded, ...]
    removed: tuple[RuleRemoved, ...]
    changed: tuple[RuleChanged, ...]
    conflicts_opened: tuple[ConflictNotice, ...]
    conflicts_closed: tuple[ConflictNotice, ...]
    unchanged_count: int
    old_fingerprint: str
    new_fingerprint: str

    @property
    def is_empty(self) -> bool:
        return (
            not self.added
            and not self.removed
            and not self.changed
            and not self.conflicts_opened
            and not self.conflicts_closed
        )

    def render(self) -> list[str]:
        """Terminal lines. One header, one line per change, in stable order."""
        header = (
            f"doctrine diff: +{len(self.added)} -{len(self.removed)} "
            f"~{len(self.changed)}, conflicts opened {len(self.conflicts_opened)} "
            f"closed {len(self.conflicts_closed)}, {self.unchanged_count} unchanged "
            f"({self.old_fingerprint[:12]} -> {self.new_fingerprint[:12]})"
        )
        if self.is_empty:
            return [header, "  no change — same doctrine, every rule cited"]

        lines = [header]
        lines.extend(entry.render() for entry in self.changed)
        lines.extend(entry.render() for entry in self.added)
        lines.extend(entry.render() for entry in self.removed)
        for notice in self.conflicts_opened:
            lines.append(
                f"! conflict opened on {notice.subject_id} / "
                f"{notice.predicate_hint} — claims "
                f"{', '.join(notice.claim_ids)} suspended pending adjudication"
            )
        for notice in self.conflicts_closed:
            lines.append(
                f"! conflict closed on {notice.subject_id} / "
                f"{notice.predicate_hint} — claims "
                f"{', '.join(notice.claim_ids)} adjudicated or retracted"
            )
        return lines

    def to_dict(self) -> dict[str, Any]:
        """JSON shape for the web face."""
        return {
            "old_fingerprint": self.old_fingerprint,
            "new_fingerprint": self.new_fingerprint,
            "unchanged_count": self.unchanged_count,
            "changes": [
                entry.to_dict()
                for entry in (*self.changed, *self.added, *self.removed)
            ],
            "conflicts_opened": [n.to_dict() for n in self.conflicts_opened],
            "conflicts_closed": [n.to_dict() for n in self.conflicts_closed],
        }


def diff(old: Doctrine, new: Doctrine) -> DoctrineDiff:
    """Compare two compiled doctrines rule-by-rule, keyed on claim identity.

    Claim IDs are content-addressed, so "same claim ID" means "same belief,
    verbatim" — a rule keyed by an unchanged claim cannot have changed text,
    which is why identity comparison is sufficient and text comparison would
    be redundant. A removed rule and an added rule sharing a subject and hint
    are paired into a :class:`RuleChanged`: the policy on that question moved
    from one governing belief to another.
    """
    old_by_id = {r.claim_id: r for r in old.rules}
    new_by_id = {r.claim_id: r for r in new.rules}

    removed_rules = [r for r in old.rules if r.claim_id not in new_by_id]
    added_rules = [r for r in new.rules if r.claim_id not in old_by_id]
    unchanged_count = sum(1 for r in new.rules if r.claim_id in old_by_id)

    # Pair removals with additions on the same (subject, hint): a replacement,
    # not two unrelated edits. Pairing is positional within each key's
    # chronologically sorted lists, which is total and therefore stable.
    def slot(rule: DoctrineRule) -> tuple[str, str]:
        return (rule.subject_id, rule.predicate_hint)

    removed_by_slot: dict[tuple[str, str], list[DoctrineRule]] = {}
    for rule in removed_rules:
        removed_by_slot.setdefault(slot(rule), []).append(rule)

    changed: list[RuleChanged] = []
    added: list[RuleAdded] = []
    for rule in added_rules:
        candidates = removed_by_slot.get(slot(rule))
        if candidates:
            changed.append(RuleChanged(old=candidates.pop(0), new=rule))
        else:
            added.append(RuleAdded(rule=rule))

    suspended_now = {
        claim_id for notice in new.conflicts for claim_id in notice.claim_ids
    }
    removed = [
        RuleRemoved(
            rule=rule,
            note=(
                "suspended by an unresolved conflict; the compiler does not pick"
                if rule.claim_id in suspended_now
                else "no longer among the committed, readable beliefs "
                "(retracted, or visibility tightened — the log says which)"
            ),
        )
        for slot_rules in removed_by_slot.values()
        for rule in slot_rules
    ]
    removed.sort(key=lambda e: (e.rule.learned_at, e.rule.claim_id))

    old_conflicts = {frozenset(n.claim_ids): n for n in old.conflicts}
    new_conflicts = {frozenset(n.claim_ids): n for n in new.conflicts}
    opened = [n for key, n in new_conflicts.items() if key not in old_conflicts]
    closed = [n for key, n in old_conflicts.items() if key not in new_conflicts]
    opened.sort(key=lambda n: (n.subject_id, n.predicate_hint, n.claim_ids))
    closed.sort(key=lambda n: (n.subject_id, n.predicate_hint, n.claim_ids))

    return DoctrineDiff(
        added=tuple(added),
        removed=tuple(removed),
        changed=tuple(changed),
        conflicts_opened=tuple(opened),
        conflicts_closed=tuple(closed),
        unchanged_count=unchanged_count,
        old_fingerprint=old.fingerprint(),
        new_fingerprint=new.fingerprint(),
    )
