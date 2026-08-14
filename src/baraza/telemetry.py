"""OpenTelemetry spans over the reasoning chain.

Both deployed services trace the path a question takes — retrieval, the
visibility filter, the model call, the citation check — so that a run can be
reconstructed afterwards from the trace rather than from a guess.

**A span never carries a quote.** Claims are recorded by
:meth:`Claim.digest`, the audience-independent SHA-256 prefix of the quote that
exists precisely so an audit trail can prove *which* text was used without
reproducing it. A trace backend is a second copy of everything you put in it,
with its own retention, its own access control, and its own export path — and
none of those route through ``readable_by``. Putting a private quote in a span
attribute would move testimony outside the boundary the entire system is built
around, quietly, in a place nobody looks.

So this module's API takes ``Claim`` objects and emits digests. There is no
function here that accepts free text about a claim, which makes the leak
difficult to write rather than merely forbidden.

Export is best-effort by design. If the Cloud Trace exporter is unavailable —
not installed, no credentials, running under ``make demo`` on a laptop — tracing
degrades to no-op spans and the request still serves. A telemetry dependency
that can take down the surface it observes is a worse trade than a missing
trace.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Sequence

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer

__all__ = [
    "configure",
    "tracer",
    "span",
    "record_claims",
    "record_audience",
    "attributes_for_run",
    "exporter_status",
]

_INSTRUMENTATION_NAME = "baraza"

# Set once per process. Recorded so ``/healthz`` can report what actually
# happened rather than what was attempted — "tracing configured" and "tracing
# exporting" are different claims and the second one is the one that matters.
_status: str = "not configured"


def exporter_status() -> str:
    """What the trace exporter is actually doing, in one phrase.

    Surfaced on the health endpoint so a missing exporter is visible rather than
    inferred from an absence of traces three days later.
    """
    return _status


def configure(service_name: str, *, project: Optional[str] = None) -> str:
    """Install a tracer provider. Idempotent; safe to call from a lifespan hook.

    Returns the resulting status string, which is also what
    :func:`exporter_status` reports afterwards.
    """
    global _status

    if _status != "not configured":
        return _status

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover - SDK is a declared dependency
        _status = "no sdk; spans are no-ops"
        return _status

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "baraza",
            "deployment.environment": os.environ.get(
                "BARAZA_ENVIRONMENT", "unspecified"
            ),
        }
    )
    provider = TracerProvider(resource=resource)

    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        exporter = CloudTraceSpanExporter(
            project_id=project or os.environ.get("BARAZA_PROJECT_ID")
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _status = "exporting to cloud trace"
    except Exception:  # noqa: BLE001
        # Every failure here is the same failure from the caller's point of
        # view: spans are recorded in-process and go nowhere. Catching broadly
        # is correct because the alternative is a service that refuses to start
        # because its observability sidecar is unhappy.
        _status = "local only; no exporter attached"

    trace.set_tracer_provider(provider)
    return _status


def tracer() -> Tracer:
    return trace.get_tracer(_INSTRUMENTATION_NAME)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """Start a span with attributes, recording exceptions before re-raising.

    Attribute values are passed through untouched, so callers are responsible
    for not handing this raw claim text — which is why claims are recorded
    through :func:`record_claims` and never as strings.
    """
    with tracer().start_as_current_span(name) as active:
        for key, value in attributes.items():
            if value is not None:
                active.set_attribute(key, value)
        try:
            yield active
        except Exception as exc:  # noqa: BLE001
            active.record_exception(exc)
            raise


def record_claims(active: Span, claims: Sequence[Any], *, key: str = "baraza.claims") -> None:
    """Attach claim identity to a span — digests and IDs, never text.

    ``claim_id`` is content-addressed over the quote, and ``digest()`` is a hash
    of the quote alone. Both let a later reader prove which record a decision
    used; neither reveals what it said.
    """
    active.set_attribute(f"{key}.count", len(claims))
    if not claims:
        return
    active.set_attribute(f"{key}.ids", [c.claim_id for c in claims])
    active.set_attribute(f"{key}.digests", [c.digest() for c in claims])


def record_audience(active: Span, audience: Any, *, withheld: int = 0) -> None:
    """Record which side of the boundary this span ran on.

    ``withheld`` is a count of records that matched but were not readable. The
    count is honest and the content is not disclosed — the same asymmetry the
    librarian's refusal path uses, applied to the trace.
    """
    active.set_attribute("baraza.audience", getattr(audience, "value", str(audience)))
    active.set_attribute("baraza.withheld_count", int(withheld))


def attributes_for_run(run_id: str, *, scheduled: bool) -> Dict[str, Any]:
    """Standard attributes for a job or scheduled run.

    ``scheduled`` is carried into the trace for the same reason it is carried
    into the event log: a Cloud Scheduler run is never counted as organic
    activity, and any query over these traces has to be able to tell the
    difference.
    """
    return {"baraza.run_id": run_id, "baraza.scheduled": bool(scheduled)}
