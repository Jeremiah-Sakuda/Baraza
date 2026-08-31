"""Doctrine byte-stability — WS3(b)'s property, next to the fold's.

Fold → doctrine compilation is deterministic, and this test is what makes that
sentence safe to say: re-serialize every instant in a golden log under
arbitrary UTC offsets and ISO spellings, shuffle the log into any arrival
order, fold, compile — and both the doctrine ``fingerprint()`` and the
rendered system prompt are **byte-identical** to the all-UTC, in-order
compile. The claim stops at the doctrine: what a model does under it is a
separately measured number, never asserted here or anywhere.

The technique mirrors ``tests/property/test_fold_stability.py``, including its
planted mixed-offset trap (``L-01``): the golden log loosens one committed
belief's visibility to ``org`` and tightens it back to ``private`` one hour
later, with the later instant serialized in a US-Central offset so it sorts
*before* the earlier one as text. A compiler downstream of an ISO-string-
ordered fold would hand the ORG audience a rule the user made private — the
doctrine would leak by sort key. The property holds because the fold orders on
epoch millis and the compiler adds no ordering of its own that could differ.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from baraza.doctrine import compile as compile_doctrine
from baraza.doctrine import render_system_prompt
from baraza.fold.graph import fold
from baraza.schema.claim import Claim, Provenance
from baraza.schema.event import Event
from baraza.schema.visibility import Audience, Visibility
from baraza_testkit import anchor as make_anchor
from baraza_testkit import (
    asserted,
    committed,
    ms,
    rejected,
    visibility_set,
)

OFFSET_MINUTES: Sequence[int] = (0, -300, -480, -210, 180, 330, 345, 780)
STYLES: Sequence[str] = ("colon", "compact", "z")

Serialize = Callable[[int], str]


def iso_at(instant: int, offset_minutes: int, style: str = "colon") -> str:
    """Serialize one instant under one offset. Serialization only, never a key."""
    stamp = datetime.fromtimestamp(
        instant / 1000, tz=timezone(timedelta(minutes=offset_minutes))
    )
    text = stamp.isoformat(timespec="seconds")
    if style == "z" and offset_minutes == 0:
        return text.replace("+00:00", "Z")
    if style == "compact":
        return re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", text)
    return text


def _utc(instant: int) -> str:
    return iso_at(instant, 0, "z")


# ------------------------------------------------------------------- instants

T_B1 = ms("2026-08-24T10:00:00Z")  # never-pad stated
T_B2 = ms("2026-08-25T10:00:00Z")  # cite-first stated
T_B3 = ms("2026-08-28T10:00:00Z")  # the colliding padding statement
T_B4 = ms("2026-08-23T09:00:00Z")  # bullet-points, later retracted
T_B5 = ms("2026-08-26T10:00:00Z")  # routing rule, the visibility trap rides it
T_FACT = ms("2026-04-01T09:00:00Z")  # a corpus fact, committed, never doctrine

T_COMMITS = ms("2026-08-28T20:00:00Z")
T_REJECT_B4 = ms("2026-08-29T09:00:00Z")

# The L-01 trap pair: one hour apart; the later one, serialized at -05:00,
# sorts earlier as text.
T_VIS_ORG = ms("2026-08-30T00:00:00Z")
T_VIS_PRIVATE = ms("2026-08-30T01:00:00Z")

BUILDER = "ent:the-builder"


# --------------------------------------------------------------------- claims


def _belief(
    ser: Serialize,
    *,
    quote: str,
    rule_text: str,
    predicate: str,
    hint: str,
    literal: str,
    turn: str,
    session: str,
    observed_at: int,
) -> Claim:
    return Claim.create(
        subject_id=BUILDER,
        predicate=predicate,
        predicate_hint=hint,
        quote=quote,
        anchor=make_anchor(session, turn),
        observed_at=ser(observed_at),
        object_literal=literal,
        provenance=Provenance.INTERVIEW,
        extra={"rule_text": rule_text},
    )


def _b1(ser: Serialize) -> Claim:
    return _belief(
        ser,
        quote="Never pad estimates. If it's three days, say three days.",
        rule_text="Never pad estimates.",
        predicate="estimation_padding",
        hint="estimation policy",
        literal="never",
        turn="turn:t-9",
        session="ses:dogfood-01",
        observed_at=T_B1,
    )


def _b2(ser: Serialize) -> Claim:
    return _belief(
        ser,
        quote="cite the source before the number, every time",
        rule_text="Cite the source before the number.",
        predicate="citation_order",
        hint="citation policy",
        literal="source-first",
        turn="turn:t-14",
        session="ses:dogfood-02",
        observed_at=T_B2,
    )


def _b3(ser: Serialize) -> Claim:
    return _belief(
        ser,
        quote="just pad the client-facing ones by 15%",
        rule_text="Pad client-facing estimates by 15%.",
        predicate="estimation_padding",
        hint="estimation policy",
        literal="pad-client-facing-15",
        turn="turn:t-31",
        session="ses:dogfood-04",
        observed_at=T_B3,
    )


def _b4(ser: Serialize) -> Claim:
    return _belief(
        ser,
        quote="put everything in bullet points",
        rule_text="Format every answer as bullet points.",
        predicate="answer_format",
        hint="preference",
        literal="bullets",
        turn="turn:t-3",
        session="ses:dogfood-01",
        observed_at=T_B4,
    )


def _b5(ser: Serialize) -> Claim:
    return _belief(
        ser,
        quote="route anything client-facing through me first",
        rule_text="Route client-facing output to the user before it goes anywhere.",
        predicate="output_routing",
        hint="routing",
        literal="user-first",
        turn="turn:t-22",
        session="ses:dogfood-03",
        observed_at=T_B5,
    )


def _fact(ser: Serialize) -> Claim:
    return Claim.create(
        subject_id="ent:treasurer",
        predicate="signing_threshold",
        predicate_hint="signing authority",
        quote="The treasurer may sign for amounts up to five hundred.",
        anchor=make_anchor("src:constitution-scan", "p.4 ¶2"),
        observed_at=ser(T_FACT),
        object_literal="500",
        provenance=Provenance.CORPUS,
    )


# IDs are content-addressed and carry no instant, so they are computed once
# under UTC. If a claim ID ever depended on a serialized instant, the golden
# fingerprints below would move under offset permutation and this file would
# fail — which is itself part of the property.
B1_ID = _b1(_utc).claim_id
B2_ID = _b2(_utc).claim_id
B3_ID = _b3(_utc).claim_id
B4_ID = _b4(_utc).claim_id
B5_ID = _b5(_utc).claim_id
FACT_ID = _fact(_utc).claim_id


# ------------------------------------------------------------------- the log

StepBuild = Callable[[Serialize], Event]

GOLDEN_LOG: Sequence[tuple[str, int, Callable[[Serialize], Event]]] = (
    ("assert-b4", T_B4, lambda ser: asserted(_b4(ser), at=ser(T_B4))),
    ("assert-b1", T_B1, lambda ser: asserted(_b1(ser), at=ser(T_B1))),
    ("assert-b2", T_B2, lambda ser: asserted(_b2(ser), at=ser(T_B2))),
    ("assert-b5", T_B5, lambda ser: asserted(_b5(ser), at=ser(T_B5))),
    ("assert-b3", T_B3, lambda ser: asserted(_b3(ser), at=ser(T_B3))),
    ("assert-fact", T_FACT, lambda ser: asserted(_fact(ser), at=ser(T_FACT))),
    ("commit-b4", T_COMMITS, lambda ser: committed(B4_ID, ser(T_COMMITS))),
    ("commit-b1", T_COMMITS + 1, lambda ser: committed(B1_ID, ser(T_COMMITS + 1))),
    ("commit-b2", T_COMMITS + 2, lambda ser: committed(B2_ID, ser(T_COMMITS + 2))),
    ("commit-b5", T_COMMITS + 3, lambda ser: committed(B5_ID, ser(T_COMMITS + 3))),
    ("commit-b3", T_COMMITS + 4, lambda ser: committed(B3_ID, ser(T_COMMITS + 4))),
    ("commit-fact", T_COMMITS + 5, lambda ser: committed(FACT_ID, ser(T_COMMITS + 5))),
    ("reject-b4", T_REJECT_B4, lambda ser: rejected(B4_ID, ser(T_REJECT_B4))),
    # The trap pair rides the routing rule: loosened to org, tightened back to
    # private one hour later. Applied backwards, B5 compiles for the ORG
    # audience — a private rule handed out by a sort key.
    (
        "visibility-org",
        T_VIS_ORG,
        lambda ser: visibility_set(B5_ID, Visibility.ORG, ser(T_VIS_ORG)),
    ),
    (
        "visibility-private",
        T_VIS_PRIVATE,
        lambda ser: visibility_set(B5_ID, Visibility.PRIVATE, ser(T_VIS_PRIVATE)),
    ),
)

STEP_COUNT = len(GOLDEN_LOG)


def materialize(offsets: Sequence[int], styles: Sequence[str]) -> list[Event]:
    """Build the golden log with one chosen offset/spelling per step."""
    events: list[Event] = []
    for (_, _, build), offset, style in zip(GOLDEN_LOG, offsets, styles, strict=True):

        def ser(instant: int, _o: int = offset, _s: str = style) -> str:
            return iso_at(instant, _o, _s)

        events.append(build(ser))
    return events


GOLDEN_EVENTS = materialize([0] * STEP_COUNT, ["z"] * STEP_COUNT)
GOLDEN_STATE = fold(GOLDEN_EVENTS)

GOLDEN_OWNER = compile_doctrine(GOLDEN_STATE, audience=Audience.OWNER)
GOLDEN_ORG = compile_doctrine(GOLDEN_STATE, audience=Audience.ORG)
GOLDEN_OWNER_FINGERPRINT = GOLDEN_OWNER.fingerprint()
GOLDEN_ORG_FINGERPRINT = GOLDEN_ORG.fingerprint()
GOLDEN_OWNER_PROMPT = render_system_prompt(GOLDEN_OWNER)
GOLDEN_ORG_PROMPT = render_system_prompt(GOLDEN_ORG)


# ---------------------------------------------------------------- the property


@given(
    offsets=st.lists(
        st.sampled_from(OFFSET_MINUTES), min_size=STEP_COUNT, max_size=STEP_COUNT
    ),
    styles=st.lists(
        st.sampled_from(STYLES), min_size=STEP_COUNT, max_size=STEP_COUNT
    ),
    order=st.permutations(list(range(STEP_COUNT))),
)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_doctrine_is_byte_identical_under_permuted_offsets_and_order(
    offsets, styles, order
):
    """The headline property: same log, any spelling, any arrival order —
    same doctrine, byte for byte, for every audience."""
    events = materialize(offsets, styles)
    shuffled = [events[i] for i in order]
    state = fold(shuffled)

    owner = compile_doctrine(state, audience=Audience.OWNER)
    org = compile_doctrine(state, audience=Audience.ORG)

    assert owner.fingerprint() == GOLDEN_OWNER_FINGERPRINT
    assert org.fingerprint() == GOLDEN_ORG_FINGERPRINT
    # The prompt is the surface a session actually runs under, so stability of
    # the hash without stability of the rendering would be a hollow property.
    assert render_system_prompt(owner) == GOLDEN_OWNER_PROMPT
    assert render_system_prompt(org) == GOLDEN_ORG_PROMPT


def test_the_golden_doctrine_is_not_vacuous():
    """Fingerprints over an empty doctrine would make the property hollow."""
    # OWNER: cite-first and the routing rule are in force; the two padding
    # statements collide and are suspended; the bullet-points belief was
    # retracted; the corpus fact never compiles.
    assert [r.claim_id for r in GOLDEN_OWNER.rules] == [B2_ID, B5_ID]
    (notice,) = GOLDEN_OWNER.conflicts
    assert set(notice.claim_ids) == {B1_ID, B3_ID}
    assert all(side.quote is not None for side in notice.sides)
    assert B4_ID not in {r.claim_id for r in GOLDEN_OWNER.rules}
    assert FACT_ID not in {r.claim_id for r in GOLDEN_OWNER.rules}
    assert GOLDEN_OWNER.withheld == 0

    # ORG: everything is private to this audience — counted, never quoted.
    assert GOLDEN_ORG.rules == ()
    assert GOLDEN_ORG.withheld == 2  # cite-first and the tightened routing rule
    (org_notice,) = GOLDEN_ORG.conflicts
    assert all(side.quote is None for side in org_notice.sides)
    assert "route anything client-facing" not in GOLDEN_ORG_PROMPT
    assert "cite the source" not in GOLDEN_ORG_PROMPT

    # And the two doctrines are genuinely different artifacts.
    assert GOLDEN_OWNER_FINGERPRINT != GOLDEN_ORG_FINGERPRINT


def test_trap_spelling_compiles_by_instant():
    """Pin the L-01 trap deterministically rather than trusting the draw.

    The tightening event is spelled in a US-Central offset so it sorts before
    the loosening event as text and after it as an instant. The ORG doctrine
    must still withhold the routing rule.
    """
    offsets = [0] * STEP_COUNT
    styles = ["z"] * STEP_COUNT
    trap_index = [label for label, _, _ in GOLDEN_LOG].index("visibility-private")
    offsets[trap_index] = -300
    styles[trap_index] = "colon"

    spelled = iso_at(T_VIS_PRIVATE, -300, "colon")
    assert spelled < iso_at(T_VIS_ORG, 0, "z")  # the text-order inversion
    assert ms(spelled) > ms(iso_at(T_VIS_ORG, 0, "z"))  # the instant order

    state = fold(materialize(offsets, styles))
    org = compile_doctrine(state, audience=Audience.ORG)
    assert org.rules == ()
    assert org.fingerprint() == GOLDEN_ORG_FINGERPRINT


def test_offset_permutation_actually_changes_the_serialization():
    """Guard against a vacuous property: the permuted inputs must differ."""
    instants = [instant for _, instant, _ in GOLDEN_LOG]
    utc = [iso_at(i, 0, "z") for i in instants]
    shifted = [iso_at(i, -300, "colon") for i in instants]
    assert utc != shifted
    assert all(a != b for a, b in zip(utc, shifted, strict=True))
    assert [ms(a) for a in utc] == [ms(b) for b in shifted]
