"""The compliance lints, verified by making each one fail.

A lint nobody has seen fail is a lint that might not work. Every structural
invariant in AGENTS.md is enforced by a regex in ``scripts/compliance.py``, and
a regex that is slightly wrong is indistinguishable from a regex that is right
until the day it matters. So each lint here is exercised the only way that
proves anything: plant the violation it exists to catch, run the real script as
a real subprocess, and require that it exits 1 and prints a ``file:line`` a
human can open. Then remove the violation and require green again — because a
lint that fires on everything is as useless as one that fires on nothing.

The probes are written and deleted inside ``try/finally``. They live under
``src/`` for a few hundred milliseconds and are named after the process that
planted them.

Note the shape of this file: the violating text is assembled from fragments at
runtime rather than written out. This module is itself inside the tree the
lints scan, and a test that plants a real model-ID literal in its own source
would fail the build it is trying to verify.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "compliance.py"
PROBE_DIR = REPO / "src" / "baraza"

_HEADER = '"""Planted compliance violation. The test that wrote this removes it."""\n'

# Each probe is (source text, 1-indexed line of the violation, expected rule).
BOUNDARY_PROBE = (
    _HEADER + "def render(claim):\n" + "    return claim." + "_quote" + "_protected\n",
    3,
    "boundary",
)
MODEL_PIN_PROBE = (
    _HEADER + 'PINNED = "' + "gem" + 'ini-0.0-planted-probe"\n',
    2,
    "model-pin",
)
TEMPORAL_PROBE = (
    _HEADER
    + "def newest(turns):\n"
    + "    return sorted(turns, key=lambda t: t.iso)[-1]\n",
    3,
    "temporal",
)


def _run(cwd: Path = REPO, script: Path = SCRIPT) -> subprocess.CompletedProcess:
    """Run the audit exactly as ``make compliance`` would, minus the PRD half."""
    return subprocess.run(
        [sys.executable, str(script), "--no-prd"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


@pytest.fixture
def probe_path() -> Path:
    """A uniquely named probe file, guaranteed removed."""
    path = PROBE_DIR / f"_compliance_probe_{os.getpid()}.py"
    try:
        yield path
    finally:
        if path.exists():
            path.unlink()


class TestBaseline:
    def test_the_tree_is_green_before_anything_is_planted(self):
        """The control. Without it, every assertion below could be a false
        positive from a violation somebody else left in the tree."""
        result = _run()
        assert result.returncode == 0, result.stdout + result.stderr
        assert "green — no findings" in result.stdout

    def test_the_audit_reports_all_four_lints_by_name(self):
        result = _run()
        for label in (
            "visibility boundary",
            "model pins",
            "temporal comparisons",
            "metrics provenance",
        ):
            assert label in result.stdout


class TestPlantedViolations:
    @pytest.mark.parametrize(
        "probe",
        [BOUNDARY_PROBE, MODEL_PIN_PROBE, TEMPORAL_PROBE],
        ids=["boundary", "model-pin", "temporal"],
    )
    def test_the_lint_bites_and_names_the_line(self, probe, probe_path):
        source, lineno, rule = probe
        relative = probe_path.relative_to(REPO)

        probe_path.write_text(source, encoding="utf-8")
        planted = _run()

        assert planted.returncode == 1, planted.stdout + planted.stderr
        assert f"[{rule}]" in planted.stdout
        assert f"{relative}:{lineno}" in planted.stdout

        probe_path.unlink()
        cleaned = _run()
        assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
        assert "green — no findings" in cleaned.stdout

    def test_two_violations_in_one_file_are_both_reported(self, probe_path):
        """A lint that stops at the first finding hides the rest of the work."""
        source = (
            _HEADER
            + 'PINNED = "' + "gem" + 'ini-0.0-planted-probe"\n'
            + "def render(claim):\n"
            + "    return claim." + "_quote" + "_protected\n"
        )
        relative = probe_path.relative_to(REPO)
        probe_path.write_text(source, encoding="utf-8")

        planted = _run()
        assert planted.returncode == 1
        assert f"{relative}:2" in planted.stdout
        assert f"{relative}:4" in planted.stdout

    def test_a_commented_out_violation_is_not_a_finding(self, probe_path):
        """The lints skip comment lines on purpose: a module docstring that
        discusses the pinned models must not fail the build. Recorded because
        the fix for an over-broad lint is usually an allowlist, and an allowlist
        is how a lint quietly stops covering the real case."""
        source = _HEADER + '# PINNED = "' + "gem" + 'ini-0.0-planted-probe"\n'
        probe_path.write_text(source, encoding="utf-8")

        assert _run().returncode == 0

    def test_prose_about_the_models_is_not_a_finding(self, probe_path):
        """The first version of the model-pin regex fired on the word 'Gemini'
        opening a docstring. This is that false positive, pinned."""
        source = (
            '"""Runs on Gemini via Vertex. Planted probe; the test removes it."""\n'
            "VALUE = 1\n"
        )
        probe_path.write_text(source, encoding="utf-8")

        assert _run().returncode == 0


class TestMetricsLint:
    """Run against a throwaway tree.

    The metrics lint reads one fixed path, so exercising it in place would mean
    editing ``docs/metrics.json`` — a committed file another session may be
    writing to at the same moment. A copy of the real script over a synthetic
    tree tests the same code without that risk.
    """

    def _tree(self, tmp_path: Path, metrics) -> Path:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "src").mkdir()
        shutil.copy(SCRIPT, tmp_path / "scripts" / "compliance.py")
        if metrics is not None:
            (tmp_path / "docs" / "metrics.json").write_text(
                json.dumps(metrics, indent=2), encoding="utf-8"
            )
        return tmp_path / "scripts" / "compliance.py"

    def test_not_yet_measured_is_green(self, tmp_path):
        script = self._tree(
            tmp_path,
            {"metrics": {"kill_survival_resumed_turn_index": "not yet measured"}},
        )
        result = _run(cwd=tmp_path, script=script)
        assert result.returncode == 0, result.stdout

    def test_a_bare_number_without_provenance_is_a_finding(self, tmp_path):
        """The defect this lint exists for: a plausible number where a measured
        one belongs."""
        script = self._tree(
            tmp_path, {"metrics": {"gemma_prefilter_survival_rate": {"value": 0.38}}}
        )
        result = _run(cwd=tmp_path, script=script)

        assert result.returncode == 1
        assert "[metrics]" in result.stdout
        assert "gemma_prefilter_survival_rate" in result.stdout
        assert "provenance" in result.stdout

    def test_an_invented_provenance_label_is_a_finding(self, tmp_path):
        script = self._tree(
            tmp_path,
            {
                "metrics": {
                    "interview_first_token_ms_replay": {
                        "value": 240,
                        "provenance": "measured on my laptop",
                        "run_id": "r-1",
                        "date": "2026-08-13",
                    }
                }
            },
        )
        result = _run(cwd=tmp_path, script=script)

        assert result.returncode == 1
        assert "measured on my laptop" in result.stdout

    def test_a_fully_provenanced_number_is_green(self, tmp_path):
        script = self._tree(
            tmp_path,
            {
                "metrics": {
                    "interview_first_token_ms_replay": {
                        "value": 240,
                        "provenance": "measured in-process",
                        "run_id": "r-1",
                        "date": "2026-08-13",
                    }
                }
            },
        )
        assert _run(cwd=tmp_path, script=script).returncode == 0

    def test_a_missing_metrics_file_is_a_finding(self, tmp_path):
        script = self._tree(tmp_path, None)
        result = _run(cwd=tmp_path, script=script)
        assert result.returncode == 1
        assert "not yet measured" in result.stdout


class TestExitCodes:
    def test_a_missing_prd_exits_two_not_one(self):
        """Exit 2 means the audit could not run; exit 1 means it found things.
        Collapsing them would let an absent contract read as a passing one."""
        if (REPO / "docs" / "PRD.md").exists():
            pytest.skip("docs/PRD.md is present in this tree; exit 2 is unreachable")
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "PRD audit could not run" in result.stdout
