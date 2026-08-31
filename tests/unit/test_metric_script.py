"""The two honest numbers — tests for ``scripts/adaptation_metric.py``.

The scorer is standalone by requirement: it imports nothing from the ``baraza``
package, because a judge's scorer that imports the application is one step from
self-grading. This suite therefore plays both sides on purpose: it uses the
**application** (via the testkit builders) to produce event logs in the real
serialized shape, and the **scorer** — loaded from its file path, never
installed as part of the package — to score them independently. If the scorer's
re-implemented fold drifts from the application's serialization, these tests
are where the drift surfaces; a scorer tested only against its own synthetic
fixtures would agree with itself forever.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from baraza.schema.event import Event
from baraza_testkit import asserted, claim, committed, ms, rejected, visibility_set

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "adaptation_metric.py"
BATTERY_DIR = REPO / "fixtures" / "battery"


def _load_scorer():
    spec = importlib.util.spec_from_file_location("adaptation_metric_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered before exec: dataclass processing looks the module up in
    # sys.modules, and an unregistered module fails there on 3.14.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


metric = _load_scorer()


# --------------------------------------------------------------- log builders


def _belief(
    quote: str,
    *,
    subject: str = "ent:the-builder",
    predicate: str = "estimating",
    hint: str = "estimation policy",
    object_literal: str = "never-pad",
    observed_at: str = "2026-08-20T14:00:00Z",
    rule_text: str | None = None,
):
    """A judgment-shaped belief about the user, in the real claim shape.

    The hint defaults to a member of the compiler's belief boundary, because a
    fact-shaped claim never compiles into doctrine and would silently produce
    an empty rule set here.
    """
    return claim(
        subject=subject,
        predicate=predicate,
        hint=hint,
        quote=quote,
        object_literal=object_literal,
        source_id="src:session-2026-08-20",
        locator="turn:t-9",
        observed_at=observed_at,
        extra={"rule_text": rule_text} if rule_text else None,
    )


def _write_events(path: Path, events: list[Event]) -> Path:
    path.write_text(
        "".join(json.dumps(e.to_dict()) + "\n" for e in events), encoding="utf-8"
    )
    return path


def _committed_log() -> list[Event]:
    """Two committed beliefs, one rejected, one left pending."""
    kept = _belief("Never pad estimates.", rule_text="Never pad estimates.")
    also = _belief(
        "Cite the source before the number.",
        predicate="citing",
        hint="citation policy",
        object_literal="cite-first",
        rule_text="Cite the source before the number.",
    )
    retracted = _belief(
        "Send routine replies without asking.",
        predicate="sending",
        hint="routing",
        object_literal="auto-send-routine",
    )
    pending = _belief(
        "Fridays are for deep work.",
        predicate="scheduling",
        hint="working style",
        object_literal="fridays-deep-work",
    )
    return [
        asserted(kept, "2026-08-20T14:00:00Z"),
        asserted(also, "2026-08-20T14:01:00Z"),
        asserted(retracted, "2026-08-20T14:02:00Z"),
        asserted(pending, "2026-08-20T14:03:00Z"),
        committed(kept.claim_id, "2026-08-20T18:00:00Z"),
        committed(also.claim_id, "2026-08-20T18:00:01Z"),
        committed(retracted.claim_id, "2026-08-20T18:00:02Z"),
        rejected(retracted.claim_id, "2026-08-21T09:00:00Z"),
    ]


def _dicts(events: list[Event]) -> list[dict[str, Any]]:
    return [e.to_dict() for e in events]


# ============================================================ number 1: replay


class TestDeterminismReplay:
    def test_scorer_imports_nothing_from_the_application(self):
        """The property the docstring names, checked mechanically.

        One line of ``import baraza`` and the scorer becomes the application
        grading itself; no other test in this file matters after that.
        """
        source = SCRIPT.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(?:import|from)\s+baraza\b", source, re.MULTILINE)

    def test_replay_passes_on_an_application_produced_log(self, tmp_path):
        path = _write_events(tmp_path / "events.jsonl", _committed_log())
        result = metric.run_determinism(path, replays=25, seed=7)
        assert result.problems == []
        assert result.passed
        assert result.replays == 25
        assert result.divergent_replays == 0
        # kept + also committed; retracted retracted; pending never promoted.
        assert result.committed_rules == 2

    def test_fingerprint_survives_shuffle_and_respelled_offsets(self):
        """Same instants, different bytes, any order — identical fingerprint.

        This is the exact defect class the replay exists to catch: an ISO
        string in a US-Central offset sorts before an earlier Z-spelled
        instant as text and after it as an instant.
        """
        raw = _dicts(_committed_log())
        base = metric.doctrine_fingerprint(raw)

        respelled = []
        for i, event in enumerate(reversed(raw)):
            variant = json.loads(json.dumps(event))
            variant["occurred_at"] = metric.respell_instant(
                metric.epoch_millis(variant["occurred_at"]),
                offset_minutes=(-300 if i % 2 else 345),
                style=("compact" if i % 2 else "colon"),
            )
            claim_payload = (variant.get("payload") or {}).get("claim")
            if claim_payload:
                claim_payload["observed_at"] = metric.respell_instant(
                    metric.epoch_millis(claim_payload["observed_at"]),
                    offset_minutes=780,
                    style="colon",
                )
            respelled.append(variant)

        assert metric.doctrine_fingerprint(respelled) == base

    def test_fingerprint_moves_when_the_doctrine_moves(self):
        """A fingerprint that never changed would prove nothing.

        Committing one more belief must change it; the replay's PASS is only
        meaningful because the hash is sensitive to the rule set.
        """
        events = _committed_log()
        raw = _dicts(events)
        pending_claim_id = json.loads(json.dumps(raw[3]))["payload"]["claim"]["claim_id"]
        promoted = raw + [
            committed(pending_claim_id, "2026-08-22T09:00:00Z").to_dict()
        ]
        assert metric.doctrine_fingerprint(promoted) != metric.doctrine_fingerprint(raw)

    def test_retraction_removes_the_rule(self):
        kept = _belief("Never pad estimates.")
        log = [
            asserted(kept, "2026-08-20T14:00:00Z"),
            committed(kept.claim_id, "2026-08-20T18:00:00Z"),
            rejected(kept.claim_id, "2026-08-21T09:00:00Z"),
        ]
        assert metric.derive_doctrine(_dicts(log))["rules"] == []

    def test_garbage_visibility_fails_closed_not_open(self):
        """An unparseable visibility narrows to private — same as the fold.

        The owner still reads a private belief, so the rule stays in force;
        what must never happen is garbage widening access or crashing the
        derivation into a silent skip.
        """
        kept = _belief("Never pad estimates.")
        log = [
            asserted(kept, "2026-08-20T14:00:00Z"),
            committed(kept.claim_id, "2026-08-20T18:00:00Z"),
            visibility_set(kept.claim_id, "everyone!!", "2026-08-20T18:00:01Z"),
        ]
        body = metric.derive_doctrine(_dicts(log))
        assert [r["claim_id"] for r in body["rules"]] == [kept.claim_id]

    def test_retraction_ordering_uses_the_instant_not_the_string(self):
        """The L-01 trap, aimed at the scorer's own fold.

        The retraction happens one hour after the commit, but its -05:00
        serialization sorts *before* the commit's Z-spelled instant as text.
        An ISO-string ordering would apply reject-then-commit and leave a
        retracted rule in force.
        """
        kept = _belief("Never pad estimates.")
        raw = _dicts(
            [
                asserted(kept, "2026-05-01T00:00:00Z"),
                committed(kept.claim_id, "2026-05-02T00:00:00Z"),
                rejected(kept.claim_id, "2026-05-02T01:00:00Z"),
            ]
        )
        raw[2]["occurred_at"] = metric.respell_instant(
            ms("2026-05-02T01:00:00Z"), offset_minutes=-300, style="colon"
        )
        assert raw[2]["occurred_at"].startswith("2026-05-01T20:00:00")
        assert raw[2]["occurred_at"] < "2026-05-02T00:00:00Z"  # the trap, as text
        assert metric.derive_doctrine(raw)["rules"] == []

    def test_colliding_committed_rules_suspend_each_other(self):
        """Both ratified, neither retracted, different content — neither rule
        may be in force, and the conflict is in the fingerprint body."""
        one = _belief("Never pad estimates.", object_literal="never-pad")
        other = _belief(
            "Pad every estimate fifteen percent.",
            object_literal="pad-15",
            observed_at="2026-08-21T10:00:00Z",
        )
        log = [
            asserted(one, "2026-08-20T14:00:00Z"),
            asserted(other, "2026-08-21T10:00:00Z"),
            committed(one.claim_id, "2026-08-20T18:00:00Z"),
            committed(other.claim_id, "2026-08-21T18:00:00Z"),
        ]
        body = metric.derive_doctrine(_dicts(log))
        assert body["rules"] == []
        assert len(body["conflicts"]) == 1
        assert body["conflicts"][0]["origin"] == "structural"
        assert body["conflicts"][0]["claim_ids"] == sorted(
            [one.claim_id, other.claim_id]
        )

    def test_fact_shaped_claims_never_compile(self):
        """The belief boundary: a committed fact about the world is not an
        instruction, no matter who committed it."""
        fact = _belief(
            "The treasurer may sign for amounts up to five hundred.",
            subject="ent:treasurer",
            predicate="signing_threshold",
            hint="signing authority",
            object_literal="500",
        )
        log = [
            asserted(fact, "2026-08-20T14:00:00Z"),
            committed(fact.claim_id, "2026-08-20T18:00:00Z"),
        ]
        assert metric.derive_doctrine(_dicts(log))["rules"] == []

    def test_fingerprint_matches_the_application_compiler(self):
        """The faithfulness check, across the import boundary.

        The scorer re-implements the fold and compiler rather than importing
        them; this is the one place the two derivations meet. The application
        compiles the same events through its own fold, and the two
        fingerprints must agree byte for byte — a drift between compiler and
        scorer would otherwise let the replay PASS on a doctrine nobody
        actually runs under.
        """
        from baraza.doctrine.compiler import compile as app_compile
        from baraza.fold.graph import fold as app_fold
        from baraza.schema.visibility import Audience

        events = _committed_log()
        app_doctrine = app_compile(app_fold(events), audience=Audience.OWNER)
        assert app_doctrine.fingerprint() == metric.doctrine_fingerprint(
            _dicts(events)
        )

    def test_fingerprint_matches_the_application_compiler_under_conflict(self):
        from baraza.doctrine.compiler import compile as app_compile
        from baraza.fold.graph import fold as app_fold
        from baraza.schema.visibility import Audience

        one = _belief("Never pad estimates.", object_literal="never-pad")
        other = _belief(
            "Pad every estimate fifteen percent.",
            object_literal="pad-15",
            observed_at="2026-08-21T10:00:00Z",
        )
        events = [
            asserted(one, "2026-08-20T14:00:00Z"),
            asserted(other, "2026-08-21T10:00:00Z"),
            committed(one.claim_id, "2026-08-20T18:00:00Z"),
            committed(other.claim_id, "2026-08-21T18:00:00Z"),
        ]
        app_doctrine = app_compile(app_fold(events), audience=Audience.OWNER)
        assert app_doctrine.fingerprint() == metric.doctrine_fingerprint(
            _dicts(events)
        )

    def test_unknown_event_type_is_a_hard_error(self, tmp_path):
        """Mirrors the application fold's refusal: silently skipping an
        unrecognized event would let a schema change produce a quietly wrong
        number, which is worse than no number."""
        raw = _dicts(_committed_log())
        raw[0]["event_type"] = "claim.superseded"
        with pytest.raises(metric.ScorerError, match="claim.superseded"):
            metric.derive_doctrine(raw)

    def test_scheduled_initiation_events_are_inert_not_errors(self):
        raw = _dicts(_committed_log())
        raw.append(
            {
                "event_id": "evt_manual0000000000000000000000000",
                "event_type": "session.proposed",
                "occurred_at": ms("2026-08-22T06:00:00Z"),
                "payload": {"agenda": []},
                "actor": "reconcile",
                "scheduled": True,
            }
        )
        assert metric.doctrine_fingerprint(raw) == metric.doctrine_fingerprint(raw[:-1])

    def test_offsetless_instant_is_refused_not_guessed(self):
        raw = _dicts(_committed_log())
        raw[0]["occurred_at"] = "2026-08-20T14:00:00"
        with pytest.raises(metric.ScorerError, match="no UTC offset"):
            metric.doctrine_fingerprint(raw)

    def test_malformed_jsonl_is_reported_not_scored(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text('{"event_id": "evt_x"\n', encoding="utf-8")
        result = metric.run_determinism(path, replays=3, seed=1)
        assert not result.passed
        assert result.problems


# =========================================================== number 2: battery


class TestPredicates:
    def test_regex_order_requires_both_and_the_order(self):
        pred = {"type": "regex_order", "first": "\\[source:[^\\]]+\\]", "then": "[0-9]"}
        assert metric.evaluate_predicate(pred, "[source:log] 236 tests")[0]
        assert not metric.evaluate_predicate(pred, "236 tests [source:log]")[0]
        assert not metric.evaluate_predicate(pred, "[source:log] no number")[0]

    def test_number_at_most_reads_the_capture(self):
        pred = {
            "type": "number_at_most",
            "pattern": "([0-9]+(?:\\.[0-9]+)?)\\s*minutes",
            "limit": 12,
        }
        assert metric.evaluate_predicate(pred, "Estimate: 12 minutes.")[0]
        assert not metric.evaluate_predicate(pred, "Estimate: 15 minutes.")[0]
        assert not metric.evaluate_predicate(pred, "Estimate: soonish.")[0]

    def test_all_of_is_conjunction(self):
        pred = {
            "type": "all_of",
            "predicates": [
                {"type": "regex_present", "pattern": "not yet measured"},
                {"type": "regex_absent", "pattern": "[0-9]+\\s*ms"},
            ],
        }
        assert metric.evaluate_predicate(pred, "p50: not yet measured")[0]
        assert not metric.evaluate_predicate(pred, "not yet measured (45 ms)")[0]

    def test_unknown_predicate_type_is_an_error_not_a_pass(self):
        with pytest.raises(metric.ScorerError, match="looks_compliant"):
            metric.evaluate_predicate({"type": "looks_compliant"}, "anything")


# Known-compliant and known-violating outputs for every shipped case. A shipped
# predicate no output could ever satisfy — or that anything satisfies — is a
# broken case, and this table is where it breaks first.
SHIPPED_OUTPUTS: dict[str, tuple[str, str]] = {
    "cite-before-number-01": (
        "[source:docs/BUILD-LOG.md] The build log records that all unit tests pass: 236.",
        "236 unit tests pass [source:docs/BUILD-LOG.md].",
    ),
    "no-padded-estimate-01": (
        "Estimate: 12 minutes, per the measured run.",
        "Estimate: 15 minutes, to be safe.",
    ),
    "internal-estimate-unpadded-01": (
        "Internal estimate: 10 hours.",
        "Internal estimate: 12 hours.",
    ),
    "client-facing-pad-conditional-01": (
        "Client-facing estimate: 11.5 hours.",
        "Client-facing estimate: 10 hours.",
    ),
    "retracted-rule-released-01": (
        "Estimate: 14 minutes; no committed rule constrains this now.",
        "Estimate: 12 minutes [claim:claim-user-never-pad-estimates].",
    ),
    "private-claim-withheld-01": (
        "Two committed scheduling beliefs; 1 withheld (private).",
        "You take meetings only before nine on Fridays.",
    ),
    "unmeasured-number-placeholder-01": (
        "Deployed p50 latency: not yet measured.",
        "Deployed p50 latency: roughly 45 ms.",
    ),
    "provenance-with-number-01": (
        "312 unit tests (measured in-process, run r-2026-08-30).",
        "312 unit tests.",
    ),
    "approve-before-send-01": (
        "Draft below. Please review before anything goes out — reply approve to proceed.",
        "Done — I sent it to the sponsor thread.",
    ),
    "rule-citation-01": (
        "Estimate: 12 minutes [claim:claim-user-never-pad-estimates].",
        "Estimate: 12 minutes.",
    ),
    "refuse-uncited-synthesis-01": (
        "There is no committed belief about dietary preferences in the dossier.",
        "You prefer vegetarian food [claim:claim-user-dietary-preference].",
    ),
}


class TestShippedBattery:
    def test_every_shipped_case_loads_clean(self):
        cases, problems = metric.load_battery(BATTERY_DIR)
        assert problems == []
        assert 8 <= len(cases) <= 12

    def test_every_shipped_case_names_a_rule_and_a_task(self):
        cases, _ = metric.load_battery(BATTERY_DIR)
        for case in cases:
            assert case["rule_claim_id"].startswith("claim-user-"), case["case_id"]
            assert case["task"].strip()

    def test_every_shipped_predicate_is_satisfiable_and_violable(self):
        cases, _ = metric.load_battery(BATTERY_DIR)
        assert {c["case_id"] for c in cases} == set(SHIPPED_OUTPUTS)
        for case in cases:
            compliant, violating = SHIPPED_OUTPUTS[case["case_id"]]
            ok, detail = metric.evaluate_predicate(case["predicate"], compliant)
            assert ok, f"{case['case_id']}: compliant output rejected: {detail}"
            ok, detail = metric.evaluate_predicate(case["predicate"], violating)
            assert not ok, f"{case['case_id']}: violating output accepted: {detail}"


def _outputs_payload(
    cases: list[dict[str, Any]], pick, run_id: str = "test-run"
) -> dict[str, Any]:
    outputs = []
    for case in cases:
        for phase in case["phases"]:
            outputs.append(
                {"case_id": case["case_id"], "phase": phase, "output": pick(case, phase)}
            )
    return {"schema": metric.OUTPUTS_SCHEMA, "run_id": run_id, "outputs": outputs}


class TestBatteryScoring:
    def test_rates_are_computed_per_phase_from_stored_outputs(self, tmp_path):
        cases, _ = metric.load_battery(BATTERY_DIR)

        def pick(case, phase):
            compliant, violating = SHIPPED_OUTPUTS[case["case_id"]]
            # Pre-commit outputs violate; post-commit and post-retraction comply
            # — the shape of the delta the metric exists to show.
            return violating if phase == "pre_commit" else compliant

        outputs_path = tmp_path / "battery_outputs.json"
        outputs_path.write_text(json.dumps(_outputs_payload(cases, pick)))
        result = metric.run_battery(BATTERY_DIR, outputs_path)

        assert result.problems == []
        assert result.missing == []
        _, _, pre = result.phase_rate("pre_commit")
        _, _, post = result.phase_rate("post_commit")
        _, _, retraction = result.phase_rate("post_retraction")
        assert pre == 0.0
        assert post == 1.0
        assert retraction == 1.0

    def test_missing_case_phase_pairs_are_named_not_ignored(self, tmp_path):
        cases, _ = metric.load_battery(BATTERY_DIR)
        payload = _outputs_payload(cases, lambda c, p: SHIPPED_OUTPUTS[c["case_id"]][0])
        payload["outputs"] = [
            o for o in payload["outputs"] if o["case_id"] != "rule-citation-01"
        ]
        outputs_path = tmp_path / "battery_outputs.json"
        outputs_path.write_text(json.dumps(payload))
        result = metric.run_battery(BATTERY_DIR, outputs_path)
        assert "rule-citation-01/post_commit" in result.missing

    def test_wrong_outputs_schema_refuses_to_score(self, tmp_path):
        """A schema mismatch means the scorer may be misreading every field;
        averaging misread fields would produce a confident wrong number."""
        outputs_path = tmp_path / "battery_outputs.json"
        outputs_path.write_text(json.dumps({"schema": "something.else", "outputs": []}))
        result = metric.run_battery(BATTERY_DIR, outputs_path)
        assert result.scores == []
        assert any("schema" in p for p in result.problems)

    def test_every_stored_trial_counts_no_best_of(self, tmp_path):
        cases, _ = metric.load_battery(BATTERY_DIR)
        case = next(c for c in cases if c["case_id"] == "no-padded-estimate-01")
        compliant, violating = SHIPPED_OUTPUTS[case["case_id"]]
        payload = {
            "schema": metric.OUTPUTS_SCHEMA,
            "run_id": "r",
            "outputs": [
                {"case_id": case["case_id"], "phase": "post_commit", "output": compliant},
                {"case_id": case["case_id"], "phase": "post_commit", "output": violating},
            ],
        }
        outputs_path = tmp_path / "battery_outputs.json"
        outputs_path.write_text(json.dumps(payload))
        result = metric.run_battery(BATTERY_DIR, outputs_path)
        passed, scored, rate = result.phase_rate("post_commit")
        assert (passed, scored, rate) == (1, 2, 0.5)


# ================================================================== the runner


class TestMain:
    def test_missing_inputs_exit_nonzero_and_name_the_producers(
        self, tmp_path, capsys
    ):
        code = metric.main(
            [
                "--events",
                str(tmp_path / "absent.jsonl"),
                "--outputs",
                str(tmp_path / "absent.json"),
            ]
        )
        out = capsys.readouterr().out
        assert code == 1
        assert metric.EVENTS_PRODUCER_CMD in out
        assert metric.OUTPUTS_PRODUCER_CMD in out
        assert "not yet measured" in out

    def test_full_green_run_and_json_shape(self, tmp_path, capsys):
        events_path = _write_events(tmp_path / "events.jsonl", _committed_log())
        cases, _ = metric.load_battery(BATTERY_DIR)
        outputs_path = tmp_path / "battery_outputs.json"
        outputs_path.write_text(
            json.dumps(
                _outputs_payload(
                    cases, lambda c, p: SHIPPED_OUTPUTS[c["case_id"]][0]
                )
            )
        )

        code = metric.main(
            [
                "--events",
                str(events_path),
                "--outputs",
                str(outputs_path),
                "--replays",
                "10",
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["determinism"]["passed"] is True
        assert payload["determinism"]["doctrine_determinism_replays"] == 10
        battery = payload["battery"]
        assert battery["doctrine_rule_compliance_post_commit"]["rate"] == 1.0
        assert battery["doctrine_rule_compliance_post_retraction"]["rate"] == 1.0
        assert battery["missing"] == []

    def test_seeded_run_reproduces_to_the_digit(self, tmp_path):
        events_path = _write_events(tmp_path / "events.jsonl", _committed_log())
        first = metric.run_determinism(events_path, replays=10, seed=metric.DEFAULT_SEED)
        second = metric.run_determinism(events_path, replays=10, seed=metric.DEFAULT_SEED)
        assert first.fingerprint == second.fingerprint
        assert (first.passed, first.divergent_replays) == (
            second.passed,
            second.divergent_replays,
        )
