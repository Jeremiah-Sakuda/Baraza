"""Defensive resolution of symbols owned by other lanes.

The web face depends on modules that are being reworked in parallel — belief
extraction in ``baraza.ingest.extract``, the interviewer in
``baraza.interview.interviewer``, and the doctrine compiler/diff in
``baraza.doctrine``. Importing those symbols at module load time would make the
web surface fail to *start* the moment a parallel lane renames something, which
is the worst possible coupling for the one surface every demo beat depends on.

So every cross-lane symbol is resolved at call time, by name, with an explicit
miss value. A missing module or attribute degrades the specific feature that
needed it — the page says so honestly — instead of taking the process down.
This is a seam for the integrate pass, not a permanent contract: once the
owning lane's surface settles, callers may tighten to a direct import.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

__all__ = ["resolve_symbol", "call_tolerant"]


def resolve_symbol(module_name: str, *candidates: str) -> Any | None:
    """Return the first attribute in ``candidates`` found on ``module_name``.

    Returns ``None`` when the module does not import or none of the candidate
    names exist. Import errors are swallowed deliberately: at this layer an
    unimportable lane module and an absent one are the same fact — the feature
    it powers is unavailable — and the caller renders that fact rather than a
    traceback.
    """
    try:
        module = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 — any import failure means "not available"
        return None
    for name in candidates:
        attr = getattr(module, name, None)
        if attr is not None:
            return attr
    return None


def call_tolerant(fn: Any, /, **kwargs: Any) -> Any:
    """Call ``fn`` with only the keyword arguments its signature accepts.

    Parallel lanes may add or drop parameters between integrate passes. Passing
    an unexpected keyword would raise ``TypeError`` and look like a bug in the
    callee; silently dropping arguments the callee never asked for is the
    behavior that keeps both sides working. Exceptions raised *inside* the call
    propagate — a callee that failed must not be mistaken for one that is
    absent.
    """
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**kwargs)
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()
    )
    if accepts_kwargs:
        return fn(**kwargs)
    accepted = {k: v for k, v in kwargs.items() if k in signature.parameters}
    return fn(**accepted)
