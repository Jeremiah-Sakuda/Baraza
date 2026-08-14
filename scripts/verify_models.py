#!/usr/bin/env python3
"""``make verify-models`` — resolve every pinned model ID against live Vertex.

A pinned literal that nobody checked is a plausible value where a verified one
belongs. ``src/baraza/schema/models.py`` says so in its own docstring and then
points here: until this script has run green against the target project, no
document in this repository may state which model version shipped.

So this script resolves **every** pin in ``ALL_PINNED`` against the live Vertex
endpoint and exits nonzero if any of them does not come back. There is no
allowlist and no ``--skip``, because the first thing a tired session does with a
skip flag is skip the pin that was actually wrong.

**Absent credentials are not a pass.** A missing project, missing ADC, or a
missing SDK exits **3** with an explanation. That is deliberately distinct from
exit 1 (a pin failed to resolve) and from exit 0, for the same reason
``scripts/compliance.py`` separates "could not run" from "ran and found
nothing": a check that never executed must never print like a check that
succeeded.

**A permission error stops the run and gets reported.** It is never routed
around by widening a scope, a key, or a service-account role — that is a named
prohibition in AGENTS.md, and it is named because widening the scope is what an
unattended agent does at 2 a.m.

Exit codes: 0 all pins resolved, 1 at least one did not, 3 the check could not
run at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

# The Makefile exports PYTHONPATH=src; this keeps a direct `python3
# scripts/verify_models.py` working too, so the instruction in models.py's
# docstring is runnable exactly as written.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

EXIT_OK = 0
EXIT_UNRESOLVED = 1
EXIT_CANNOT_RUN = 3


# Failure text that means "we never got to ask", not "the pin is wrong". The
# SDK constructs a client lazily, so absent credentials do not surface until the
# first call — and they then surface once per pin, which reads exactly like four
# bad model IDs. Reporting that as a pin failure would be the same defect this
# script exists to prevent, one level up: a check that never ran, printed as a
# check that ran and found something.
_NEVER_ASKED = (
    "default credentials",
    "could not automatically determine credentials",
    "unauthenticated",
    "invalid_grant",
    "reauth",
    "credentials were not found",
    "401",
    "permission denied",
    "403",
)


@dataclass
class Outcome:
    role: str
    model_id: str
    surface: str
    resolved: bool
    detail: str = ""

    @property
    def never_asked(self) -> bool:
        low = self.detail.lower()
        return any(marker in low for marker in _NEVER_ASKED)

    def render(self) -> str:
        mark = "ok  " if self.resolved else "FAIL"
        return f"  {mark}  {self.role:<10} {self.model_id:<26} [{self.surface}]"


def _cannot_run(message: str) -> int:
    print("model pin verification")
    print("=" * 72)
    print()
    print("  COULD NOT RUN — this is not a pass.")
    print()
    for line in message.splitlines():
        print(f"  {line}")
    print()
    print(
        "  Until this script runs green against the target project, no document\n"
        "  in this repository may state which model version shipped."
    )
    return EXIT_CANNOT_RUN


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve every pinned model ID against live Vertex AI."
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--location", default=None, help="override the Vertex region for this check"
    )
    args = parser.parse_args(argv)

    try:
        from baraza.schema import models
    except ImportError as exc:  # pragma: no cover - environment dependent
        return _cannot_run(
            f"cannot import baraza.schema.models: {exc}\n"
            "Run from the repository root, or `make install` first."
        )

    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover
        return _cannot_run(
            f"the google-genai SDK is not installed: {exc}\n"
            "It is declared in pyproject.toml; run `make install`."
        )

    try:
        project = models.project_id()
    except RuntimeError as exc:
        return _cannot_run(str(exc))

    location = args.location or models.location()

    try:
        client = genai.Client(vertexai=True, project=project, location=location)
    except Exception as exc:  # noqa: BLE001 - the message is the product here
        return _cannot_run(
            f"could not construct a Vertex client for project {project!r} in "
            f"{location!r}:\n{exc}\n"
            "Most often this is absent application-default credentials. "
            "Authenticate as yourself\n"
            "(`gcloud auth application-default login`) rather than widening a "
            "service account."
        )

    print("model pin verification")
    print("=" * 72)
    print(f"  project   {project}")
    print(f"  location  {location}")
    print()

    outcomes: List[Outcome] = []
    for pin in models.ALL_PINNED:
        model_id = pin.resolved()
        try:
            client.models.get(model=model_id)
            outcomes.append(
                Outcome(
                    role=pin.env_var.removeprefix("BARAZA_MODEL_").lower(),
                    model_id=model_id,
                    surface=pin.surface,
                    resolved=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
            outcomes.append(
                Outcome(
                    role=pin.env_var.removeprefix("BARAZA_MODEL_").lower(),
                    model_id=model_id,
                    surface=pin.surface,
                    resolved=False,
                    detail=detail,
                )
            )

    # Every pin failing for the same access reason is an access problem, not
    # four wrong model IDs. Say which one it is; the two have different fixes
    # and only one of them is a finding about this repository.
    failures = [o for o in outcomes if not o.resolved]
    if failures and len(failures) == len(outcomes) and all(o.never_asked for o in failures):
        return _cannot_run(
            f"every pin failed identically before Vertex answered, against "
            f"project {project!r} in {location!r}:\n"
            f"  {failures[0].detail}\n"
            "That is an access problem, not a verdict on the pins — none of them "
            "was actually checked.\n"
            "Authenticate as yourself (`gcloud auth application-default login`). "
            "If this is a permission\n"
            "error, report it; do not widen a scope, a key, or a "
            "service-account role to unblock."
        )

    if args.json:
        print(
            json.dumps(
                {
                    "project": project,
                    "location": location,
                    "pins": [
                        {
                            "role": o.role,
                            "model_id": o.model_id,
                            "surface": o.surface,
                            "resolved": o.resolved,
                            "detail": o.detail,
                        }
                        for o in outcomes
                    ],
                },
                indent=2,
            )
        )

    for outcome in outcomes:
        print(outcome.render())
        if not outcome.resolved:
            print(f"        {outcome.detail}")
            if outcome.surface == "vertex-endpoint":
                print(
                    "        This pin names a self-deployed endpoint. It resolves "
                    "only while that endpoint\n"
                    "        is up, and the endpoint is scripted up and down inside "
                    "a supervised session\n"
                    "        rather than left running. Bring it up and re-run; do "
                    "not exempt the pin."
                )
            if "permission" in outcome.detail.lower() or "denied" in outcome.detail.lower():
                print(
                    "        Permission error. Report it; do not widen a scope, a "
                    "key, or a role to\n"
                    "        unblock — that is a named prohibition, and it is named "
                    "for a reason."
                )

    failed = [o for o in outcomes if not o.resolved]
    print()
    print("=" * 72)
    if failed:
        print(f"{len(failed)} of {len(outcomes)} pin(s) did not resolve")
        return EXIT_UNRESOLVED
    print(f"all {len(outcomes)} pin(s) resolved against live Vertex")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
