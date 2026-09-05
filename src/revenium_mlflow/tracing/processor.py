"""The public span processor, defined so that it cannot be installed empty.

Phase 3 (ATTR-01 through ATTR-11) implements this class. Phase 1 publishes the
name, the base class, and one guarantee: **the constructor raises.**

That guarantee is the sharpest instance of OI-02 in the SDK. Every other
unimplemented callable here fails at the point a caller uses it, which is loud
and local. A processor is different — it is *registered*, once, and then invoked
by OpenTelemetry for every span in the process forever after. A constructible
stub could be attached to MLflow's tracer provider, would observe every span,
would record nothing, and would produce no error anywhere. The integration would
look installed. The invoice would be missing traffic. So construction fails
outright rather than deferring the failure to a method that nothing in the
process ever calls directly.

Importing ``opentelemetry.sdk.trace`` at module scope is expected and permitted:
it is the public location of the ``SpanProcessor`` base class, it registers no
global state, and it opens no socket. Importing ``mlflow`` at module scope is
not permitted (D-12) — ``import revenium_mlflow`` must stay inert, and the
MLflow capability probe belongs to configure time.
"""

from opentelemetry.sdk.trace import SpanProcessor

__all__ = ["ReveniumAttributionSpanProcessor"]

_PHASE_3 = (
    "not implemented until Phase 3 (Attribution Context and Span Processor). "
    "It raises on construction rather than existing as an empty processor, "
    "because an empty processor can be installed, observes every span in the "
    "process, records nothing, and reports no error while doing it."
)


class ReveniumAttributionSpanProcessor(SpanProcessor):
    """Stamps Revenium attribution onto spans as they start.

    **Attribution is written in ``on_start`` and never in ``on_end`` (ATTR-02).**
    This is measured behaviour, not a stylistic preference: ``Span.end()``
    freezes the span's attributes before ``on_end`` is called, and ``on_end``
    receives an immutable ``ReadableSpan``. A write there is discarded, and
    MLflow suppresses the warning that would otherwise reveal it — so the
    mistake produces spans that export successfully and carry no attribution at
    all. Phase 3's implementation lives in ``on_start`` for that reason and the
    reason is recorded here, where anyone editing the class will read it.

    The class is public because the contract names it: an advanced user may
    register it on a tracer provider they own. :func:`configure_dual_export`
    remains the supported entry point for everyone else.
    """

    def __init__(self) -> None:
        """Always raises in Phase 1.

        Raises:
            NotImplementedError: Always. See the module docstring for why this
                is a hard failure rather than a permissive stub.
        """
        raise NotImplementedError(f"ReveniumAttributionSpanProcessor is {_PHASE_3}")
