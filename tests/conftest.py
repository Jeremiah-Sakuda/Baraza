"""Test-suite bootstrap.

Puts ``tests/`` and ``src/`` on ``sys.path`` explicitly. Pytest would place
``tests/`` there on its own as a side effect of collecting this conftest, but
that behaviour depends on the import mode and on which directory the run
started from — the kind of implicit thing that works until someone runs a
single test file directly. ``src/`` is added so the suite runs identically
whether or not the package was installed with ``make install``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent
_SRC = _REPO / "src"

for _entry in (str(_TESTS), str(_SRC)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
