"""The doctrine layer — committed beliefs compiled into a session policy.

Two modules, one contract:

``compiler`` folds a :class:`~baraza.fold.graph.GraphState` into a
:class:`~baraza.doctrine.compiler.Doctrine` — the rules the agent works under,
each carrying the claim ID, verbatim quote, anchor, and instant that justify
it. Pure and byte-stable: same log, same doctrine, every rule cited.

``diff`` compares two compiled doctrines and names the causal claim behind
every change. It is a doctrine diff, never an output diff.
"""

from baraza.doctrine.compiler import (
    BELIEF_HINTS,
    ConflictNotice,
    ConflictSide,
    Doctrine,
    DoctrineRule,
    compile,
    render_system_prompt,
)
from baraza.doctrine.diff import (
    DoctrineDiff,
    RuleAdded,
    RuleChanged,
    RuleRemoved,
    diff,
)

__all__ = [
    "BELIEF_HINTS",
    "ConflictNotice",
    "ConflictSide",
    "Doctrine",
    "DoctrineDiff",
    "DoctrineRule",
    "RuleAdded",
    "RuleChanged",
    "RuleRemoved",
    "compile",
    "diff",
    "render_system_prompt",
]
