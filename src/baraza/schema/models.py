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
from typing import Dict, Final, Tuple

__all__ = [
    "ModelPin",
    "REASONING",
    "FAST",
    "PREFILTER",
    "EMBEDDING",
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

REASONING: Final[ModelPin] = ModelPin(
    model_id="gemini-3.5-pro",
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

EMBEDDING: Final[ModelPin] = ModelPin(
    model_id="text-embedding-005",
    role=(
        "Claim-level embeddings for blocking-key expansion. Claims are embedded; "
        "the corpus is not. There is no vector database — brute-force top-k over "
        "a few thousand claim vectors held in memory, and the arithmetic that "
        "makes that correct is stated in the README rather than implied."
    ),
    env_var="BARAZA_MODEL_EMBEDDING",
    surface="vertex",
)

ALL_PINNED: Final[Tuple[ModelPin, ...]] = (REASONING, FAST, PREFILTER, EMBEDDING)

_BY_ROLE: Final[Dict[str, ModelPin]] = {
    "reasoning": REASONING,
    "fast": FAST,
    "prefilter": PREFILTER,
    "embedding": EMBEDDING,
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
    """Vertex region. Defaults to us-central1, overridable per session."""
    return os.environ.get("BARAZA_LOCATION", "us-central1")
