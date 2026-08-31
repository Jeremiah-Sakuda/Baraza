"""The web face — server-rendered surfaces for the session, dossier, doctrine
and approval views.

Rendering lives here as pure functions from plain data to HTML strings, so the
two services (interview and dossier) share one visual system and the templates
are testable without a running server. There is no SPA framework and no CDN
dependency: a judge's browser receives complete pages, and the only script is a
small inline poller — a page that renders nothing without a bundle is a page
that fails exactly when someone unfamiliar opens it.

Boundary note: nothing in this package reads a quote directly. Every quote a
view renders was produced upstream by ``claim.quote_for(audience)``; a view that
receives ``None`` renders a withheld placeholder, never an empty citation.
"""

from baraza.web import views
from baraza.web.defensive import resolve_symbol

__all__ = ["views", "resolve_symbol"]
