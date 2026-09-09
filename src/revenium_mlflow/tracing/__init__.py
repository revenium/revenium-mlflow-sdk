"""Internal package holding the OTLP half of the SDK.

Internal in the sense that no user should import from it: every name below is
re-exported flat from :mod:`revenium_mlflow`, which is the published import path
(D-01). The package exists so the internal structure can change without changing
that path.

**This package must never import the sibling ``metering`` package, and that
package must never import this one.** The separation is load-bearing rather than
tidy: the OTLP path needs no Revenium HTTP credential, so keeping it free of the
metering client is what lets a user install and validate trace export before
they hold a write-scope key — and what lets ``validate_connection()`` return
partial diagnostics instead of failing outright. Both directions are asserted by
AST walks in ``tests/unit/test_attribution_signature.py`` and
``tests/unit/test_public_surface.py``.

The two packages share only :mod:`revenium_mlflow.config`,
:mod:`revenium_mlflow.errors` and :mod:`revenium_mlflow.attributes`, none of
which imports anything outside the standard library.
"""

from .attribution import attribution
from .install import ReveniumExportHandle, configure_tracing
from .processor import ReveniumAttributionSpanProcessor

__all__ = [
    "ReveniumAttributionSpanProcessor",
    "ReveniumExportHandle",
    "attribution",
    "configure_tracing",
]
