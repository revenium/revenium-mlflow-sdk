"""Internal package holding the Revenium-HTTP half of the SDK.

Internal in the sense that no user should import from it: both names below are
re-exported flat from :mod:`revenium_mlflow`, which is the published import path
(D-01). The package exists so the internal structure can change without changing
that path.

**This package must never import the sibling OTLP package, and that package must
never import this one.** The separation keeps the OTLP export path installable
and usable with no Revenium HTTP credential at all — a user can configure trace
export and validate it before they ever hold a write-scope key, and
``validate_connection()`` can return partial diagnostics rather than failing
outright. Both directions are asserted by AST walks in
``tests/unit/test_attribution_signature.py`` and
``tests/unit/test_public_surface.py``.

Nothing here constructs an HTTP client or opens a socket at import time. The
adapter over ``revenium-python-sdk`` arrives in Phase 5 and imports its
dependency lazily inside function bodies (D-12), because that package logs at
ERROR on import when ``REVENIUM_METERING_API_KEY`` is unset.
"""

from .jobs import report_job_outcome
from .tools import meter_tool_span

__all__ = ["meter_tool_span", "report_job_outcome"]
