#!/usr/bin/env python3
"""BAR-330 AC 2 — the standalone adaptation scorer. ``make adaptation-metric``.

**This file imports nothing from the ``baraza`` package, and that is the entire
point of it.** Not a stylistic preference, not a build-time convenience: a
metric computed by an application over its own configured personas is one step
from the hardcoded-literal-displayed-as-a-real-count defect class, because the
same code that decided how hard to push also decided how hard it pushed. So the
application emits a labelled transcript and stops. The number is computed here,
by a script whose only inputs are files a judge can open in a text editor, using
stdlib alone, and whose whole source is short enough to read in one sitting.

If this file ever grows a line importing from the application, the property it
exists to establish is gone and no amount of test coverage brings it back.

**The definition, stated so it can be checked rather than trusted.**

    mean follow-up depth (persona) = mean(turn.follow_up_depth)
                                     over turns where role == "agent"

``follow_up_depth`` is 0 on a question drawn from the agenda and *n* on the
*n*-th consecutive clarifier about the same item. Divergence turns are agent
turns and are included at the depth they occurred at — they are part of the
pressure the interviewer applied, and excluding them would flatter a persona
that triggered a lot of them. The exact numerator and denominator are printed
alongside the mean so the figure reproduces to the digit rather than to the
rounding.

**The adaptation moment** is derived here, not read from a summary field: the
turns are ordered on their integer ``occurred_at`` (BAR-309 — never on the ISO
string beside it) and the first turn whose recorded ``follow_up_budget`` differs
from the previous turn's is the moment. The transcript also carries the
interviewer's own note on that turn; the two are printed together precisely so a
disagreement between them would be visible.

Exit codes: 0 scored at least one transcript, 1 nothing scoreable (no
transcripts, wrong schema, or malformed turns). "No transcripts committed yet"
is a red target on purpose — a green target that scored nothing is the failure
this project keeps naming.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

EXPECTED_SCHEMA = "baraza.transcript.v1"
AGENT_ROLE = "agent"
FOLLOW_UP_KIND = "follow_up"

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "transcripts"


@dataclass
class Moment:
    """A turn at which the follow-up budget moved."""

    turn_id: str
    index: int
    from_budget: int
    to_budget: int
    answers_seen: int
    terse_answers: int
    expansive_answers: int
    terse_ratio: float
    recorded_reason: str = ""

    def render(self) -> str:
        direction = "raised" if self.to_budget > self.from_budget else "lowered"
        return (
            f"turn {self.turn_id}: budget {direction} "
            f"{self.from_budget}→{self.to_budget} after {self.answers_seen} "
            f"answer(s) — {self.terse_answers} terse, {self.expansive_answers} "
            f"expansive, terse ratio {self.terse_ratio:.2f}"
        )


@dataclass
class Score:
    """One persona's transcript, scored."""

    path: Path
    persona_id: str
    style: str
    role: str
    agent_turns: int = 0
    officer_turns: int = 0
    depth_total: int = 0
    follow_up_turns: int = 0
    divergence_turns: int = 0
    agenda_turns: int = 0
    agenda_items: int = 0
    budget_trajectory: List[int] = field(default_factory=list)
    moments: List[Moment] = field(default_factory=list)
    llm_source: str = "unknown"
    paced: bool = True
    stop_reason: str = ""
    problems: List[str] = field(default_factory=list)

    @property
    def mean_follow_up_depth(self) -> Optional[float]:
        if self.agent_turns == 0:
            return None
        return self.depth_total / self.agent_turns

    @property
    def first_moment(self) -> Optional[Moment]:
        return self.moments[0] if self.moments else None


def _fail(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr)


def load_transcripts(directory: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    if not directory.exists():
        return []
    loaded: List[Tuple[Path, Dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            loaded.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError as exc:
            _fail(f"{path}: not valid JSON ({exc})")
    return loaded


def score_transcript(path: Path, payload: Dict[str, Any]) -> Score:
    persona = payload.get("persona") or {}
    run = payload.get("run") or {}

    score = Score(
        path=path,
        persona_id=persona.get("persona_id", path.stem),
        style=persona.get("style", "unknown"),
        role=persona.get("role", ""),
        llm_source=run.get("llm_source", "unknown"),
        paced=bool(run.get("paced", False)),
        stop_reason=run.get("stop_reason", ""),
    )

    if payload.get("schema") != EXPECTED_SCHEMA:
        score.problems.append(
            f"schema is {payload.get('schema')!r}, expected {EXPECTED_SCHEMA!r}; "
            "refusing to average fields this scorer may be misreading"
        )
        return score

    turns = payload.get("turns")
    if not isinstance(turns, list) or not turns:
        score.problems.append("no turns")
        return score

    # BAR-309: order on the integer instant, never on the ISO string that sits
    # beside it in the same record. The index is the tiebreaker.
    try:
        ordered = sorted(turns, key=lambda t: (int(t["occurred_at"]), int(t["index"])))
    except (KeyError, TypeError, ValueError) as exc:
        score.problems.append(f"turns are not orderable on occurred_at/index: {exc}")
        return score

    items: List[str] = []
    previous_budget: Optional[int] = None

    for turn in ordered:
        adaptation = turn.get("adaptation") or {}
        budget = adaptation.get("follow_up_budget")
        if budget is None:
            score.problems.append(
                f"turn {turn.get('turn_id')} carries no adaptation state; the "
                "adaptation moment cannot be located without it"
            )
            return score
        budget = int(budget)

        if not score.budget_trajectory or score.budget_trajectory[-1] != budget:
            score.budget_trajectory.append(budget)

        if previous_budget is not None and budget != previous_budget:
            score.moments.append(
                Moment(
                    turn_id=str(turn.get("turn_id")),
                    index=int(turn.get("index", -1)),
                    from_budget=previous_budget,
                    to_budget=budget,
                    answers_seen=int(adaptation.get("answers_seen", 0)),
                    terse_answers=int(adaptation.get("terse_answers", 0)),
                    expansive_answers=int(adaptation.get("expansive_answers", 0)),
                    terse_ratio=float(adaptation.get("terse_ratio", 0.0)),
                    recorded_reason=str(turn.get("adaptation_change") or ""),
                )
            )
        previous_budget = budget

        item_id = turn.get("agenda_item_id")
        if item_id and item_id not in items:
            items.append(item_id)

        if turn.get("role") != AGENT_ROLE:
            score.officer_turns += 1
            continue

        score.agent_turns += 1
        score.depth_total += int(turn.get("follow_up_depth", 0))
        kind = turn.get("kind")
        if kind == FOLLOW_UP_KIND:
            score.follow_up_turns += 1
        elif kind == "divergence":
            score.divergence_turns += 1
        elif kind == "agenda":
            score.agenda_turns += 1

    score.agenda_items = len(items)
    return score


# ------------------------------------------------------------------ printing


def render(scores: Sequence[Score]) -> List[str]:
    lines: List[str] = []
    for score in scores:
        lines.append("")
        header = f"{score.persona_id}"
        if score.role:
            header += f" — {score.role}"
        lines.append(header)
        lines.append(f"  transcript              {score.path}")

        if score.problems:
            for problem in score.problems:
                lines.append(f"  UNSCOREABLE             {problem}")
            continue

        mean = score.mean_follow_up_depth
        lines.extend(
            [
                f"  style declared          {score.style}",
                f"  agenda items covered    {score.agenda_items}",
                f"  agent turns             {score.agent_turns} "
                f"({score.agenda_turns} agenda, {score.follow_up_turns} follow-up, "
                f"{score.divergence_turns} divergence)",
                f"  officer turns           {score.officer_turns}",
                f"  MEAN FOLLOW-UP DEPTH    {mean:.4f}   "
                f"= {score.depth_total} / {score.agent_turns}",
                "  follow-up budget        "
                + " → ".join(str(b) for b in score.budget_trajectory),
            ]
        )
        if score.moments:
            lines.append(f"  adaptation moment: turn {score.moments[0].turn_id}")
            for moment in score.moments:
                lines.append(f"      {moment.render()}")
                if moment.recorded_reason:
                    lines.append(f"      transcript note: {moment.recorded_reason}")
        else:
            lines.append(
                "  adaptation moment: NONE — the budget never moved in this run"
            )
        lines.append(
            f"  model side              {score.llm_source}"
            + ("  (recorded replay)" if "cassette" in score.llm_source else "")
        )
        lines.append(
            "  pacing                  "
            + ("simulated typing pace" if score.paced else "DISABLED (not human pace)")
        )
        if score.stop_reason:
            lines.append(f"  run ended because       {score.stop_reason}")
    return lines


def render_comparison(scores: Sequence[Score]) -> List[str]:
    """The claim the metric exists to support, or its absence.

    BAR-330 says a terse answerer earns more clarifiers and an expansive one
    earns fewer. That is a statement about two numbers, so it is checked against
    the two numbers rather than asserted next to them.
    """
    usable = {
        s.style: s for s in scores if not s.problems and s.mean_follow_up_depth is not None
    }
    terse = usable.get("terse")
    expansive = usable.get("expansive")
    if terse is None or expansive is None:
        return [
            "",
            "direction: not checkable — needs one scoreable 'terse' transcript and "
            "one 'expansive' transcript.",
        ]

    t_mean = terse.mean_follow_up_depth or 0.0
    e_mean = expansive.mean_follow_up_depth or 0.0
    holds = t_mean > e_mean
    return [
        "",
        "direction check (BAR-330: terse earns more clarifiers, expansive fewer)",
        f"  terse      {terse.persona_id:<22} {t_mean:.4f}",
        f"  expansive  {expansive.persona_id:<22} {e_mean:.4f}",
        f"  difference {t_mean - e_mean:+.4f}  — "
        + ("holds" if holds else "DOES NOT HOLD in these transcripts"),
    ]


def to_json(scores: Sequence[Score]) -> Dict[str, Any]:
    return {
        "definition": (
            "mean follow-up depth = mean(turn.follow_up_depth) over turns with "
            'role == "agent"'
        ),
        "personas": [
            {
                "persona_id": s.persona_id,
                "style": s.style,
                "transcript": str(s.path),
                "mean_follow_up_depth": s.mean_follow_up_depth,
                "depth_total": s.depth_total,
                "agent_turns": s.agent_turns,
                "follow_up_turns": s.follow_up_turns,
                "agenda_items_covered": s.agenda_items,
                "budget_trajectory": s.budget_trajectory,
                "adaptation_moment_turn_id": (
                    s.first_moment.turn_id if s.first_moment else None
                ),
                "adaptation_moments": [
                    {
                        "turn_id": m.turn_id,
                        "from_budget": m.from_budget,
                        "to_budget": m.to_budget,
                        "answers_seen": m.answers_seen,
                        "terse_ratio": m.terse_ratio,
                    }
                    for m in s.moments
                ],
                "llm_source": s.llm_source,
                "paced": s.paced,
                "problems": s.problems,
            }
            for s in scores
        ],
    }


# -------------------------------------------------------------------- runner


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "BAR-330 adaptation scorer. Standalone by requirement: imports "
            "nothing from the baraza package."
        )
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=str(DEFAULT_DIR),
        help="directory of committed replay transcripts",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    directory = Path(args.directory)
    transcripts = load_transcripts(directory)

    if not transcripts:
        print("BAR-330 adaptation metric")
        print("=" * 72)
        print(f"  no transcripts in {directory}")
        print()
        print("  Transcripts are generated, never authored. Produce them with:")
        print("      make demo-interview REPLAY=1 PERSONA=terse")
        print("      make demo-interview REPLAY=1 PERSONA=expansive")
        print()
        print("  Until then the metric is not yet measured, and this target is")
        print("  red on purpose — a green scorer that scored nothing is worse")
        print("  than a red one, because only one of those gets noticed.")
        return 1

    scores = [score_transcript(path, payload) for path, payload in transcripts]

    if args.json:
        print(json.dumps(to_json(scores), indent=2))
        return 0 if any(not s.problems for s in scores) else 1

    print("BAR-330 adaptation metric — standalone scorer (no application imports)")
    print("=" * 72)
    print(f"source     {directory}  ({len(scores)} transcript(s))")
    print(
        'definition mean follow-up depth = mean(turn.follow_up_depth) over turns '
        'with role == "agent"'
    )
    for line in render(scores):
        print(line)
    for line in render_comparison(scores):
        print(line)
    print()
    print("=" * 72)

    scoreable = [s for s in scores if not s.problems]
    if not scoreable:
        print("no transcript could be scored")
        return 1
    print(f"scored {len(scoreable)} of {len(scores)} transcript(s)")
    print("reproduce with: make adaptation-metric")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
