"""Pinned model identifiers — the one place a model name is written.

Every Gemini call in Baraza resolves its model through this module. Nothing
else in the codebase contains a model-ID string literal, and
``scripts/compliance.py`` fails the build if one appears elsewhere.

**Runtime is Gemini, exclusively.** Gemini 3.5 Pro and Flash via Vertex AI. No
other model provider appears in any execution path. Gemma is a separate,
declared component — the ingestion relevance pre-filter (BAR-303) — and is
listed here so the additional-model bonus claim traces to code rather than to a
sentence in a README.

**Verification, not assumption.** These literals are pinned, but a pinned
literal that nobody checked is a plausible value where a verified one belongs.
``scripts/verify_models.py`` resolves every ID in ``ALL_PINNED`` against the
live Vertex endpoint and exits nonzero on any that does not resolve. Run it
before any submission artifact quotes a model name:

    make verify-models

Until that script has been run green against the target project, no document in
this repository may state which model version shipped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

__all__ = [
    "ModelPin",
    "REASONING",
    "FAST",
    "PREFILTER",
    "ALL_PINNED",
    "resolve",
    "location",
    "project_id",
]


@dataclass(frozen=True, slots=True)
class ModelPin:
    """A model, its role, and the environment variable that may override it."""

    model_id: str
    role: str
    env_var: str
    surface: str
    """``vertex`` for Vertex AI Model Garden / GenAI on Vertex; ``vertex-endpoint``
    for a self-deployed endpoint that must be scripted up and down within a
    session."""

    def resolved(self) -> str:
        """The effective ID, allowing an env override for a supervised session.

        The override exists so a measurement session can pin a specific
        revision without a code change. Whichever value is used is recorded in
        ``docs/metrics.json`` alongside the run ID.
        """
        return os.environ.get(self.env_var, self.model_id)


# --------------------------------------------------------------------- pins

# Live verification 2026-08-31 (user-token REST + google-genai SDK against
# project baraza-2026): gemini-3.5-pro DOES NOT EXIST in the Vertex catalog —
# the pro line is gemini-3.1-pro-preview (< 3.5). gemini-3.7-flash and
# gemini-3.5-flash both resolve and answer at location=global; both satisfy the
# hackathon's "Gemini 3.5 or newer" floor. gemini-embedding-001 resolves
# (3072 dims). The original pins were plausible literals nobody had checked —
# the exact defect class this module's docstring warns about.
REASONING: Final[ModelPin] = ModelPin(
    model_id="gemini-3.7-flash",
    role=(
        "Contradiction adjudication (BAR-320), agenda synthesis, the divergence "
        "turn, and successor-mode synthesis. Every call that must be right more "
        "than it must be quick."
    ),
    env_var="BARAZA_MODEL_REASONING",
    surface="vertex",
)

FAST: Final[ModelPin] = ModelPin(
    model_id="gemini-3.5-flash",
    role=(
        "Claim extraction over corpus chunks, entity alias proposals, and the "
        "interviewer's clarifying-follow-up turns, where first-token latency is "
        "the binding constraint (BAR-330)."
    ),
    env_var="BARAZA_MODEL_FAST",
    surface="vertex",
)

PREFILTER: Final[ModelPin] = ModelPin(
    model_id="gemma-3-12b-it",
    role=(
        "BAR-303 ingestion relevance pre-filter: keep|drop per chunk before any "
        "Gemini call, so the expensive extraction pass never sees the 60%+ of a "
        "chat export that is scheduling noise. Runs behind the stub|gemma flag; "
        "the survival rate is measured in a supervised session and is "
        "'not yet measured' until then."
    ),
    env_var="BARAZA_MODEL_PREFILTER",
    surface="vertex-endpoint",
)

# There was a fourth pin here — a text-embedding model, for "blocking-key
# expansion in detection". It was removed rather than kept, and the reason is the
# rule at the top of docs/compliance.md: a pin is a claim, and this one had no
# code behind it. `build_block` in reconcile/detect.py retrieves on exact
# subject ∪ object ∪ predicate_hint with alias edges resolved at query time.
# Nothing embedded anything, nothing computed a top-k, and no module imported the
# pin. Publishing it made three documents describe a component that did not
# exist, which is the defect this module was written to make impossible.
#
# Recorded as a negative decision in the README rather than silently dropped.

ALL_PINNED: Final[tuple[ModelPin, ...]] = (REASONING, FAST, PREFILTER)

_BY_ROLE: Final[dict[str, ModelPin]] = {
    "reasoning": REASONING,
    "fast": FAST,
    "prefilter": PREFILTER,
}


def resolve(role: str) -> str:
    """Look up a model ID by role name.

    Raises on an unknown role rather than falling back to a default — a typo
    should not silently route a reasoning call to a cheaper model.
    """
    try:
        return _BY_ROLE[role].resolved()
    except KeyError as exc:
        raise KeyError(
            f"unknown model role {role!r}; known roles: {sorted(_BY_ROLE)}"
        ) from exc


# ------------------------------------------------------------------ project

def project_id() -> str:
    """The GCP project. Never defaulted — an unset project is a stop condition.

    Defaulting here would let a misconfigured session write to the wrong
    project, and "widen the scope to unblock" is a named prohibition.
    """
    value = os.environ.get("BARAZA_PROJECT_ID") or os.environ.get(
        "GOOGLE_CLOUD_PROJECT"
    )
    if not value:
        raise RuntimeError(
            "BARAZA_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) is unset. Set it "
            "explicitly; this is not defaulted on purpose."
        )
    return value


def location() -> str:
    """Vertex location for MODEL calls. Defaults to ``global``.

    Not the Cloud Run region. Verified live 2026-08-31: every current Gemini
    model in this project's catalog serves from location ``global`` and returns
    404 from ``us-central1`` — the original regional default made every pinned
    ID unresolvable regardless of which model was named. Infra (Cloud Run,
    Scheduler, Artifact Registry) remains regional and is configured
    separately in deploy/.
    """
    return os.environ.get("BARAZA_LOCATION", "global")
