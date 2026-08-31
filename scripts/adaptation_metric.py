#!/usr/bin/env python3
"""The two honest numbers. ``make adaptation-metric``.

**This file imports nothing from the ``baraza`` package, and that is the entire
point of it.** Not a stylistic preference, not a build-time convenience: a
judge's scorer that imports the application is one step from self-grading,
because the same code that produced the artifact would also be deciding what
the artifact means. So the application emits files and stops. Everything below
is computed here, by a script whose only inputs are files a judge can open in a
text editor, using stdlib alone, and whose whole source is short enough to read
in one sitting. If this file ever grows a line importing from the application,
the property it exists to establish is gone and no amount of test coverage
brings it back.

It computes two numbers, and only these two:

**1. Doctrine determinism** (``same doctrine, every rule cited`` — never "same
behavior"; model compliance with a doctrine is a separate, probabilistic
question and is number 2). Given the session events JSONL, this script
re-derives the doctrine fingerprint N times under shuffled event order and
randomly permuted serialized UTC offsets, and PASSES only if every replay
produces the identical fingerprint. The fold and fingerprint here are an
**independent re-implementation** from the raw event JSON — deliberately not a
call into the application's fold — kept faithful to the serialized shapes in
``src/baraza/schema/event.py`` and the doctrine compiler (read, never
imported). What this proves is a property of the *event log and the derivation
rule*: the committed-rule set is a pure function of the log's content,
insensitive to arrival order and to how any instant happened to be spelled. It
does not prove anything about model output, and does not claim to.

**2. Doctrine rule compliance**, scored over a battery of fixed tasks. Each
battery case (``fixtures/battery/*.json``) names the doctrine rule it
exercises (by claim ID) and an **objective predicate** over the output text —
regex/structural, no judgment calls. The application (or a human at the
keyboard) runs the battery tasks and stores the raw outputs; this script only
*scores* the stored outputs, per phase: before the rule's belief committed,
after it committed, and after it was retracted. It never calls a model, so the
number cannot be quietly regenerated until it looks good. If the rate is
imperfect, the imperfect rate is printed — the policy-doctrine gap is real and
showing it honestly is the mitigation.

Exit codes: 0 both numbers computed and determinism PASSED; 1 an input was
missing or malformed, or determinism FAILED — the message names the exact
command that produces the missing input. A red target that says why is the
point; a green target that scored nothing is the failure this project keeps
naming.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

# ``make demo`` (offline end-to-end) appends here; the live dogfooding loop
# mirrors to the same shape. First existing candidate wins.
EVENT_LOG_CANDIDATES = ("out/events.jsonl", "fixtures/transcripts/events.jsonl")
EVENTS_PRODUCER_CMD = "make demo"

BATTERY_DIR_DEFAULT = REPO / "fixtures" / "battery"
OUTPUTS_DEFAULT = REPO / "out" / "battery_outputs.json"
OUTPUTS_PRODUCER_CMD = "make battery-run"

CASE_SCHEMA = "baraza.battery.case.v1"
OUTPUTS_SCHEMA = "baraza.battery.outputs.v1"
PHASES = ("pre_commit", "post_commit", "post_retraction")

DEFAULT_REPLAYS = 50
# Seeded so the run reproduces to the digit; pass --seed to draw fresh
# permutations. 309 after BAR-309, the invariant the replay exercises.
DEFAULT_SEED = 309


# =====================================================================
# Temporal normalization — minimal re-implementation of the contract in
# src/baraza/schema/temporal.py (BAR-309). Instants compare as integer epoch
# millis, UTC; ISO strings are serialization only. Re-implemented rather than
# imported so a defect in the application's normalizer cannot silently agree
# with itself here.
# =====================================================================

# Values below this are epoch seconds, at or above it epoch millis — the same
# ceiling the application documents for mixed chat-export/serialized inputs.
_EPOCH_SECONDS_CEILING = 10_000_000_000

_HAS_OFFSET = re.compile(r"(?:[Zz]|[+-]\d{2}:?\d{2})$")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ScorerError(ValueError):
    """An input this scorer refuses to guess about."""


def epoch_millis(value: Any, *, where: str = "instant") -> int:
    """Normalize an instant to integer epoch millis, UTC — or refuse loudly.

    An offsetless ISO string is rejected, not guessed: a wrong instant is a
    silent correctness defect, and this scorer exists to catch exactly the
    class of bug where two spellings of one instant order differently.
    """
    if isinstance(value, bool) or value is None:
        raise ScorerError(f"{where}: {value!r} is not an instant")
    if isinstance(value, (int, float)):
        if abs(value) < _EPOCH_SECONDS_CEILING:
            return int(round(value * 1000))
        return int(round(value))
    if isinstance(value, str):
        raw = value.strip()
        if _DATE_ONLY.match(raw):
            parsed = datetime.fromisoformat(raw).replace(tzinfo=UTC)
            return int(round(parsed.timestamp() * 1000))
        if not _HAS_OFFSET.search(raw):
            raise ScorerError(
                f"{where}: ISO string {raw!r} carries no UTC offset; refusing to guess"
            )
        normalized = raw[:-1] + "+00:00" if raw[-1] in "Zz" else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ScorerError(f"{where}: unparseable instant {raw!r}") from exc
        return int(round(parsed.timestamp() * 1000))
    raise ScorerError(f"{where}: unsupported instant type {type(value).__name__}")


# =====================================================================
# The doctrine fold + fingerprint — independent re-implementation.
#
# Faithful to the serialized event shapes in src/baraza/schema/event.py and to
# the derivation in src/baraza/doctrine/compiler.py (both READ, neither
# imported — that is the point). Each JSONL line is {event_id, event_type,
# occurred_at, payload, actor, scheduled}; total order is (occurred_at millis,
# event_id). Claim lifecycle: claim.asserted enters at its serialized tier
# (idempotent on claim_id), claim.committed / claim.rejected re-tier,
# claim.visibility_set applies the recorded visibility and fails CLOSED (to
# "private") on an unparseable value.
#
# The doctrine derived here is the compiler's, for the OWNER audience (the
# dossier's own subject, who reads everything, so nothing is withheld): only
# belief-shaped committed claims compile; colliding rules suspend each other
# rather than being adjudicated; agreeing restatements deduplicate to the
# earliest statement. The fingerprint hashes the same body the application's
# Doctrine.fingerprint() hashes, so a divergence between this scorer and the
# compiler over the same log is itself detectable — the faithfulness test in
# tests/unit/test_metric_script.py compares the two digests directly.
# =====================================================================

_VISIBILITY_VALUES = frozenset({"private", "successor", "org", "public"})
_AUDIENCE = "owner"

# The belief boundary, mirrored from the compiler: a claim is belief-shaped —
# eligible to become doctrine — iff its provenance is "interview" or its
# normalized predicate_hint is in this set. Exact match on the lowercased,
# stripped hint, never substring: a boundary you can wander across by phrasing
# is not a boundary.
_BELIEF_HINTS = frozenset(
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

# Open interval sentinels for validity overlap, [from, until).
_MIN_INSTANT = -(2**62)
_MAX_INSTANT = 2**62

# Events that exist in the log but do not shape the doctrine. Listed
# explicitly: an event type in neither this set nor the handled set is a hard
# error, mirroring the application fold's refusal to skip what it does not
# understand. "session.proposed" is the scheduled-initiation event.
_DOCTRINE_INERT_EVENTS = frozenset(
    {
        "claim.adjudicated",
        "entity.alias_linked",
        "heartbeat",
        "session.opened",
        "session.turn",
        "session.closed",
        "session.proposed",
    }
)

# Claim payload fields that carry instants. Normalized before hashing so the
# fingerprint depends on *when*, never on how the when was spelled.
_CLAIM_INSTANT_FIELDS = ("observed_at", "valid_from", "valid_until")


def _fold(
    raw_events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Fold raw event dicts into (claims, contradictions), both by ID."""
    ordered = sorted(
        raw_events,
        key=lambda e: (
            epoch_millis(e.get("occurred_at"), where=f"event {e.get('event_id')}"),
            str(e.get("event_id", "")),
        ),
    )

    claims: dict[str, dict[str, Any]] = {}
    contradictions: dict[str, dict[str, Any]] = {}
    for event in ordered:
        kind = event.get("event_type")
        payload = event.get("payload") or {}

        if kind == "claim.asserted":
            claim = dict(payload.get("claim") or {})
            claim_id = claim.get("claim_id")
            if not claim_id:
                raise ScorerError(f"event {event.get('event_id')}: claim has no claim_id")
            # Deterministic event IDs make re-assertion idempotent; first wins.
            claims.setdefault(claim_id, claim)
        elif kind in ("claim.committed", "claim.rejected"):
            tier = "committed" if kind == "claim.committed" else "rejected"
            existing = claims.get(payload.get("claim_id", ""))
            if existing is not None:
                existing["tier"] = tier
        elif kind == "claim.visibility_set":
            existing = claims.get(payload.get("claim_id", ""))
            if existing is not None:
                raw_vis = payload.get("visibility")
                # Fail closed: an unparseable visibility narrows, never widens.
                existing["visibility"] = (
                    raw_vis if raw_vis in _VISIBILITY_VALUES else "private"
                )
        elif kind == "contradiction.detected":
            contradiction = dict(payload.get("contradiction") or {})
            cid = contradiction.get("contradiction_id")
            if cid:
                contradictions.setdefault(cid, contradiction)
        elif kind == "contradiction.resolved":
            existing_c = contradictions.get(payload.get("contradiction_id", ""))
            if existing_c is not None:
                existing_c["status"] = "resolved"
        elif kind in _DOCTRINE_INERT_EVENTS:
            continue
        else:
            raise ScorerError(
                f"event {event.get('event_id')}: unhandled event type {kind!r}; "
                "a new event type must teach this scorer before it can be scored"
            )
    return claims, contradictions


def _is_belief_shaped(claim: dict[str, Any]) -> bool:
    if claim.get("provenance") == "interview":
        return True
    return str(claim.get("predicate_hint") or "").strip().lower() in _BELIEF_HINTS


def _blocking_key(claim: dict[str, Any]) -> str:
    hint = str(claim.get("predicate_hint") or "").strip().lower()
    return f"{claim.get('subject_id')}|{hint}"


def _content_key(claim: dict[str, Any]) -> str:
    """What a rule says, for conflict counting and deduplication only."""
    extra = claim.get("extra")
    wording = extra.get("rule_text") if isinstance(extra, dict) else None
    if isinstance(wording, str) and wording.strip():
        base = wording
    else:
        base = (
            f"{claim.get('predicate')}|"
            f"{claim.get('object_literal') or claim.get('object_id') or ''}"
        )
    return " ".join(base.split()).lower()


def _rule_text(claim: dict[str, Any]) -> str:
    """Extraction-authored imperative wording, or the mechanical fallback."""
    extra = claim.get("extra")
    wording = extra.get("rule_text") if isinstance(extra, dict) else None
    if isinstance(wording, str) and wording.strip():
        return " ".join(wording.split())
    body = claim.get("object_literal") or claim.get("object_id") or ""
    return f"{str(claim.get('predicate', '')).replace('_', ' ')}: {body}"


def _observed_key(claim: dict[str, Any]) -> tuple[int, str]:
    claim_id = str(claim.get("claim_id"))
    return (
        epoch_millis(claim.get("observed_at"), where=f"{claim_id}.observed_at"),
        claim_id,
    )


def _validity_overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Half-open [from, until) overlap; None bounds are open."""

    def bound(claim: dict[str, Any], fld: str, sentinel: int) -> int:
        value = claim.get(fld)
        if value is None:
            return sentinel
        return epoch_millis(value, where=f"{claim.get('claim_id')}.{fld}")

    a_from, a_until = bound(a, "valid_from", _MIN_INSTANT), bound(a, "valid_until", _MAX_INSTANT)
    b_from, b_until = bound(b, "valid_from", _MIN_INSTANT), bound(b, "valid_until", _MAX_INSTANT)
    return a_from < b_until and b_from < a_until


def derive_doctrine(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold raw event dicts into the compiler's owner-audience doctrine body.

    Mirrors ``doctrine/compiler.py`` step for step: committed AND
    belief-shaped claims compile; colliding rules (structural or ledger) are
    suspended, both sides, with a conflict entry instead of an adjudication;
    agreeing restatements deduplicate to the earliest statement; rules order
    chronologically by learning with the claim ID as tiebreak. The owner reads
    every visibility, so ``withheld`` is structurally zero here — a nonzero
    count would mean this scorer was compiling for someone other than the
    dossier's own subject.

    Returns the exact body ``Doctrine.fingerprint()`` hashes, so the two
    digests are comparable across the import boundary.
    """
    claims, contradictions = _fold(raw_events)
    beliefs = [
        c
        for c in claims.values()
        if c.get("tier") == "committed" and _is_belief_shaped(c)
    ]

    suspended: set[str] = set()
    notices: list[dict[str, Any]] = []
    seen_sets: set[frozenset[str]] = set()

    def notice(sides: list[dict[str, Any]], origin: str) -> dict[str, Any]:
        first = sides[0]
        return {
            "subject_id": first.get("subject_id"),
            "predicate_hint": str(first.get("predicate_hint") or "").strip().lower(),
            "origin": origin,
            "claim_ids": sorted(str(c.get("claim_id")) for c in sides),
            # Side-order IDs, used only to reproduce the compiler's notice
            # ordering; stripped before hashing.
            "_side_ids": [str(c.get("claim_id")) for c in sides],
        }

    # Structural: same blocking key, different content, overlapping validity.
    groups: dict[str, list[dict[str, Any]]] = {}
    for claim in beliefs:
        groups.setdefault(_blocking_key(claim), []).append(claim)
    for _, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        ordered_members = sorted(members, key=_observed_key)
        involved: set[str] = set()
        for i, a in enumerate(ordered_members):
            for b in ordered_members[i + 1 :]:
                if _content_key(a) == _content_key(b):
                    continue  # agreement, handled by deduplication
                if not _validity_overlaps(a, b):
                    continue  # different periods are history, not a dispute
                involved.update((str(a["claim_id"]), str(b["claim_id"])))
        if not involved:
            continue
        sides = [c for c in ordered_members if str(c["claim_id"]) in involved]
        id_set = frozenset(involved)
        suspended.update(involved)
        if id_set not in seen_sets:
            seen_sets.add(id_set)
            notices.append(notice(sides, "structural"))

    # Ledger: open contradictions whose every side is a live committed belief.
    by_id = {str(c["claim_id"]): c for c in beliefs}
    for cid in sorted(contradictions):
        contradiction = contradictions[cid]
        if contradiction.get("status") != "open":
            continue
        claim_ids = [str(x) for x in contradiction.get("claim_ids") or []]
        pool = [claims.get(x) for x in claim_ids]
        if any(p is None or p.get("tier") == "rejected" for p in pool):
            continue  # a retracted side retracts the dispute with it
        sides = [by_id[x] for x in claim_ids if x in by_id]
        if len(sides) < 2 or len(sides) != len(claim_ids):
            continue
        id_set = frozenset(str(c["claim_id"]) for c in sides)
        suspended.update(id_set)
        if id_set in seen_sets:
            continue
        seen_sets.add(id_set)
        notices.append(notice(sorted(sides, key=_observed_key), "ledger"))

    notices.sort(
        key=lambda n: (
            str(n["subject_id"]),
            n["predicate_hint"],
            tuple(n["_side_ids"]),
        )
    )
    for entry in notices:
        del entry["_side_ids"]

    # Deduplicate agreeing restatements to the earliest statement.
    kept: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in beliefs:
        if str(claim["claim_id"]) in suspended:
            continue
        key = (_blocking_key(claim), _content_key(claim))
        incumbent = kept.get(key)
        if incumbent is None or _observed_key(claim) < _observed_key(incumbent):
            kept[key] = claim

    rules: list[dict[str, Any]] = []
    for claim in kept.values():
        anchor = claim.get("anchor") or {}
        rules.append(
            {
                "claim_id": str(claim["claim_id"]),
                "rule": _rule_text(claim),
                "anchor": anchor.get("locator", ""),
                "source_id": anchor.get("source_id", ""),
                "learned_at": _observed_key(claim)[0],
            }
        )
    rules.sort(key=lambda r: (r["learned_at"], r["claim_id"]))

    return {
        "audience": _AUDIENCE,
        "rules": rules,
        "conflicts": notices,
        "withheld": 0,
    }


def doctrine_fingerprint(raw_events: list[dict[str, Any]]) -> str:
    """SHA-256 over the canonical JSON of the derived doctrine body.

    Byte-compatible with the application's ``Doctrine.fingerprint()`` for the
    owner audience: same body, same key order, same separators.
    """
    body = json.dumps(
        derive_doctrine(raw_events), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# =====================================================================
# The determinism replay.
# =====================================================================

# Serialization offsets, in minutes. Half- and three-quarter-hour zones are
# included because non-whole-hour offsets are where naive string handling
# breaks, and +13:00 crosses the date line opposite to -08:00.
_OFFSET_MINUTES = (0, -300, -480, -210, 180, 330, 345, 780)
_OFFSET_STYLES = ("colon", "compact", "z")


def respell_instant(instant_ms: int, offset_minutes: int, style: str) -> str:
    """One instant, one arbitrary legal ISO-8601 spelling. Serialization only."""
    stamp = datetime.fromtimestamp(
        instant_ms / 1000, tz=timezone(timedelta(minutes=offset_minutes))
    )
    text = stamp.isoformat(timespec="milliseconds")
    if style == "z" and offset_minutes == 0:
        return text.replace("+00:00", "Z")
    if style == "compact":
        return re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", text)
    return text


def _permute_offsets(
    raw_events: list[dict[str, Any]], rng: random.Random
) -> list[dict[str, Any]]:
    """Rewrite every serialized instant under a random offset and spelling.

    Same instants, different bytes. A derivation that ever compares the bytes
    instead of the instants produces a different fingerprint here — that is
    the defect the replay exists to catch.
    """
    variant = copy.deepcopy(raw_events)
    for event in variant:
        instant = epoch_millis(event.get("occurred_at"), where="occurred_at")
        event["occurred_at"] = respell_instant(
            instant, rng.choice(_OFFSET_MINUTES), rng.choice(_OFFSET_STYLES)
        )
        claim = (event.get("payload") or {}).get("claim")
        if isinstance(claim, dict):
            for fld in _CLAIM_INSTANT_FIELDS:
                if claim.get(fld) is not None:
                    claim[fld] = respell_instant(
                        epoch_millis(claim[fld], where=fld),
                        rng.choice(_OFFSET_MINUTES),
                        rng.choice(_OFFSET_STYLES),
                    )
    return variant


@dataclass
class DeterminismResult:
    events_path: Path
    event_count: int = 0
    committed_rules: int = 0
    replays: int = 0
    fingerprint: str = ""
    divergent_replays: int = 0
    passed: bool = False
    problems: list[str] = field(default_factory=list)


def run_determinism(events_path: Path, replays: int, seed: int) -> DeterminismResult:
    result = DeterminismResult(events_path=events_path)

    raw_events: list[dict[str, Any]] = []
    for lineno, line in enumerate(
        events_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw_events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            result.problems.append(f"{events_path}:{lineno}: not valid JSON ({exc})")
            return result

    result.event_count = len(raw_events)
    if not raw_events:
        result.problems.append(f"{events_path} holds zero events; nothing to replay")
        return result

    try:
        result.fingerprint = doctrine_fingerprint(raw_events)
        result.committed_rules = len(derive_doctrine(raw_events)["rules"])
    except ScorerError as exc:
        result.problems.append(str(exc))
        return result

    rng = random.Random(seed)
    for _ in range(replays):
        variant = _permute_offsets(raw_events, rng)
        rng.shuffle(variant)
        try:
            replay_fp = doctrine_fingerprint(variant)
        except ScorerError as exc:
            result.problems.append(f"replay failed to derive: {exc}")
            return result
        if replay_fp != result.fingerprint:
            result.divergent_replays += 1

    result.replays = replays
    result.passed = result.divergent_replays == 0
    return result


# =====================================================================
# The compliance battery.
# =====================================================================


def evaluate_predicate(predicate: dict[str, Any], output: str) -> tuple[bool, str]:
    """Apply one objective predicate to one stored output.

    Every predicate type is mechanical — regex or arithmetic over the text.
    There is deliberately no "looks compliant" type: a predicate a human must
    interpret is a judgment call wearing a pass/fail costume.

    Returns (passed, detail) where detail says what was checked, so a
    disputed score can be re-derived by eye.
    """
    kind = predicate.get("type")
    flags = re.IGNORECASE if predicate.get("ignore_case") else 0

    if kind == "regex_present":
        pattern = predicate["pattern"]
        return (
            re.search(pattern, output, flags) is not None,
            f"requires a match of /{pattern}/",
        )

    if kind == "regex_absent":
        pattern = predicate["pattern"]
        return (
            re.search(pattern, output, flags) is None,
            f"forbids any match of /{pattern}/",
        )

    if kind == "regex_order":
        first, then = predicate["first"], predicate["then"]
        m_first = re.search(first, output, flags)
        m_then = re.search(then, output, flags)
        ok = (
            m_first is not None
            and m_then is not None
            and m_first.start() < m_then.start()
        )
        return ok, f"requires /{first}/ to match before /{then}/"

    if kind in ("number_at_most", "number_at_least"):
        pattern = predicate["pattern"]
        limit = float(predicate["limit"])
        match = re.search(pattern, output, flags)
        if match is None or not match.groups():
            return False, f"requires a numeric capture from /{pattern}/; none found"
        try:
            value = float(match.group(1))
        except ValueError:
            return False, f"capture {match.group(1)!r} from /{pattern}/ is not numeric"
        if kind == "number_at_most":
            return value <= limit, f"requires captured {value} <= {limit}"
        return value >= limit, f"requires captured {value} >= {limit}"

    if kind == "all_of":
        subs = predicate.get("predicates") or []
        details: list[str] = []
        ok = True
        for sub in subs:
            sub_ok, sub_detail = evaluate_predicate(sub, output)
            ok = ok and sub_ok
            details.append(("PASS " if sub_ok else "fail ") + sub_detail)
        return ok, "; ".join(details)

    raise ScorerError(f"unknown predicate type {kind!r}")


@dataclass
class CaseScore:
    case_id: str
    rule_claim_id: str
    phase: str
    passed: bool
    detail: str


@dataclass
class BatteryResult:
    battery_dir: Path
    outputs_path: Path
    cases: int = 0
    scores: list[CaseScore] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # "case_id/phase" pairs
    problems: list[str] = field(default_factory=list)

    def phase_rate(self, phase: str) -> tuple[int, int, float | None]:
        scored = [s for s in self.scores if s.phase == phase]
        passed = sum(1 for s in scored if s.passed)
        rate = (passed / len(scored)) if scored else None
        return passed, len(scored), rate


def load_battery(battery_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    cases: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in sorted(battery_dir.glob("*.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path}: not valid JSON ({exc})")
            continue
        if case.get("schema") != CASE_SCHEMA:
            problems.append(
                f"{path}: schema is {case.get('schema')!r}, expected {CASE_SCHEMA!r}"
            )
            continue
        required = ("case_id", "rule_claim_id", "task", "predicate")
        missing = [k for k in required if not case.get(k)]
        if missing:
            problems.append(f"{path}: missing {', '.join(missing)}")
            continue
        phases = case.get("phases", list(PHASES))
        bad_phases = [p for p in phases if p not in PHASES]
        if bad_phases:
            problems.append(f"{path}: unknown phase(s) {bad_phases}")
            continue
        case["phases"] = phases
        case["_path"] = str(path)
        cases.append(case)
    return cases, problems


def run_battery(battery_dir: Path, outputs_path: Path) -> BatteryResult:
    result = BatteryResult(battery_dir=battery_dir, outputs_path=outputs_path)

    cases, problems = load_battery(battery_dir)
    result.problems.extend(problems)
    result.cases = len(cases)
    if not cases:
        result.problems.append(f"no scoreable battery cases in {battery_dir}")
        return result

    try:
        payload = json.loads(outputs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.problems.append(f"{outputs_path}: not valid JSON ({exc})")
        return result
    if payload.get("schema") != OUTPUTS_SCHEMA:
        result.problems.append(
            f"{outputs_path}: schema is {payload.get('schema')!r}, "
            f"expected {OUTPUTS_SCHEMA!r}; refusing to score what this scorer "
            "may be misreading"
        )
        return result

    outputs: dict[tuple[str, str], list[str]] = {}
    for entry in payload.get("outputs") or []:
        case_id = entry.get("case_id")
        phase = entry.get("phase")
        text = entry.get("output")
        if not case_id or phase not in PHASES or not isinstance(text, str):
            result.problems.append(
                f"{outputs_path}: malformed output entry {entry!r}"
            )
            continue
        outputs.setdefault((case_id, phase), []).append(text)

    for case in cases:
        for phase in case["phases"]:
            recorded = outputs.get((case["case_id"], phase))
            if not recorded:
                result.missing.append(f"{case['case_id']}/{phase}")
                continue
            # Every stored trial counts; scoring only the best would be
            # cherry-picking with extra steps.
            for text in recorded:
                try:
                    passed, detail = evaluate_predicate(case["predicate"], text)
                except ScorerError as exc:
                    result.problems.append(f"{case['_path']}: {exc}")
                    break
                result.scores.append(
                    CaseScore(
                        case_id=case["case_id"],
                        rule_claim_id=case["rule_claim_id"],
                        phase=phase,
                        passed=passed,
                        detail=detail,
                    )
                )
    return result


# =====================================================================
# Rendering.
# =====================================================================


def render_determinism(result: DeterminismResult | None) -> list[str]:
    lines = ["", "1. DOCTRINE DETERMINISM — same doctrine, every rule cited"]
    if result is None:
        lines += [
            "   NOT RUN — no session events JSONL found.",
            f"   Looked for: {', '.join(EVENT_LOG_CANDIDATES)}",
            f"   Produce one with:  {EVENTS_PRODUCER_CMD}",
        ]
        return lines
    lines.append(f"   events        {result.events_path}  ({result.event_count} events)")
    if result.problems:
        for problem in result.problems:
            lines.append(f"   UNSCOREABLE   {problem}")
        return lines
    lines += [
        f"   committed     {result.committed_rules} rule(s) in the derived doctrine",
        f"   fingerprint   {result.fingerprint}",
        f"   replays       {result.replays} — shuffled order, permuted UTC offsets",
        (
            "   RESULT        PASS — every replay reproduced the fingerprint"
            if result.passed
            else f"   RESULT        FAIL — {result.divergent_replays} of "
            f"{result.replays} replay(s) diverged"
        ),
    ]
    return lines


def render_battery(result: BatteryResult | None) -> list[str]:
    lines = ["", "2. DOCTRINE RULE COMPLIANCE — objective predicates, stored outputs"]
    if result is None:
        lines += [
            f"   NOT RUN — {OUTPUTS_DEFAULT.relative_to(REPO)} does not exist.",
            "   This scorer never calls a model; the battery outputs must be",
            "   recorded first. Produce them with:",
            f"       {OUTPUTS_PRODUCER_CMD}",
            "   Until then this number is not yet measured — red on purpose.",
        ]
        return lines
    lines.append(f"   battery       {result.battery_dir}  ({result.cases} case(s))")
    lines.append(f"   outputs       {result.outputs_path}")
    for problem in result.problems:
        lines.append(f"   PROBLEM       {problem}")
    if result.scores:
        for phase in PHASES:
            passed, scored, rate = result.phase_rate(phase)
            if rate is None:
                lines.append(f"   {phase:<16} not yet measured (no stored outputs)")
            else:
                lines.append(
                    f"   {phase:<16} {rate * 100:6.1f}%   = {passed} / {scored} trial(s)"
                )
        failures = [s for s in result.scores if not s.passed]
        if failures:
            lines.append("   failed trials:")
            for score in failures:
                lines.append(
                    f"     {score.case_id} [{score.phase}] rule "
                    f"{score.rule_claim_id}: {score.detail}"
                )
    if result.missing:
        lines.append(
            "   missing outputs (applicable case/phase pairs never recorded):"
        )
        for item in result.missing:
            lines.append(f"     {item}")
    return lines


def to_json(
    determinism: DeterminismResult | None, battery: BatteryResult | None
) -> dict[str, Any]:
    det: dict[str, Any]
    if determinism is None:
        det = {"ran": False, "produce_with": EVENTS_PRODUCER_CMD}
    else:
        det = {
            "ran": not determinism.problems,
            "events_path": str(determinism.events_path),
            "event_count": determinism.event_count,
            "committed_rules": determinism.committed_rules,
            "doctrine_determinism_replays": determinism.replays,
            "fingerprint": determinism.fingerprint,
            "divergent_replays": determinism.divergent_replays,
            "passed": determinism.passed,
            "problems": determinism.problems,
        }

    bat: dict[str, Any]
    if battery is None:
        bat = {"ran": False, "produce_with": OUTPUTS_PRODUCER_CMD}
    else:
        rates: dict[str, Any] = {}
        for phase in PHASES:
            passed, scored, rate = battery.phase_rate(phase)
            rates[f"doctrine_rule_compliance_{phase}"] = (
                "not yet measured"
                if rate is None
                else {"rate": rate, "passed": passed, "trials": scored}
            )
        bat = {
            "ran": not battery.problems,
            "battery_dir": str(battery.battery_dir),
            "outputs_path": str(battery.outputs_path),
            "cases": battery.cases,
            **rates,
            "missing": battery.missing,
            "problems": battery.problems,
            "trials": [
                {
                    "case_id": s.case_id,
                    "rule_claim_id": s.rule_claim_id,
                    "phase": s.phase,
                    "passed": s.passed,
                }
                for s in battery.scores
            ],
        }
    return {"determinism": det, "battery": bat}


# =====================================================================
# Runner.
# =====================================================================


def _default_events_path() -> Path | None:
    for candidate in EVENT_LOG_CANDIDATES:
        path = REPO / candidate
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "The two honest numbers: doctrine determinism replay and doctrine "
            "rule compliance. Standalone by requirement: imports nothing from "
            "the baraza package."
        )
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help=f"session events JSONL (default: first of {', '.join(EVENT_LOG_CANDIDATES)})",
    )
    parser.add_argument(
        "--battery",
        type=Path,
        default=BATTERY_DIR_DEFAULT,
        help="directory of battery case files",
    )
    parser.add_argument(
        "--outputs",
        type=Path,
        default=OUTPUTS_DEFAULT,
        help="recorded battery outputs (this script never calls a model)",
    )
    parser.add_argument(
        "--replays", type=int, default=DEFAULT_REPLAYS, help="determinism replay count"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="RNG seed for the replay permutations (seeded so a rerun reproduces)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    events_path = args.events
    if events_path is None:
        events_path = _default_events_path()
    elif not (events_path.exists() and events_path.stat().st_size > 0):
        events_path = None

    determinism = (
        run_determinism(events_path, args.replays, args.seed)
        if events_path is not None
        else None
    )
    battery = (
        run_battery(args.battery, args.outputs) if args.outputs.exists() else None
    )

    determinism_green = determinism is not None and determinism.passed
    battery_green = battery is not None and not battery.problems and bool(
        battery.scores
    )
    exit_code = 0 if (determinism_green and battery_green) else 1

    if args.json:
        print(json.dumps(to_json(determinism, battery), indent=2))
        return exit_code

    print("The two honest numbers — standalone scorer (no application imports)")
    print("=" * 72)
    for line in render_determinism(determinism):
        print(line)
    for line in render_battery(battery):
        print(line)
    print()
    print("=" * 72)
    if exit_code == 0:
        print("both numbers computed. reproduce with: make adaptation-metric")
    else:
        print("RED — see above for what is missing or diverged, and the exact")
        print("command that produces each missing input. A red target that says")
        print("why beats a green one that scored nothing.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
