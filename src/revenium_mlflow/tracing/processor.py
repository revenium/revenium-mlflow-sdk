"""The public span processor: attribution, written at span start and nowhere else.

Phase 1 published this class with one guarantee — **the constructor raises** —
and plan 03-01 replaced that guarantee with the behaviour it was standing in for.
The reason the stub was a raise rather than an empty processor is worth keeping
in view now that the class does something, because it describes this class's
whole failure mode: a processor is *registered*, once, and then invoked by
OpenTelemetry for every span in the process forever after. One that observes
every span and records nothing produces no error anywhere. The integration looks
installed. The invoice is missing traffic. Every design decision below is chosen
against that shape rather than against an exception someone would have noticed.

Importing ``opentelemetry.sdk.trace`` at module scope is expected and permitted:
it is the public location of the ``SpanProcessor`` base class, it registers no
global state, and it opens no socket. Importing ``mlflow`` at module scope is
not permitted (D-12) — ``import revenium_mlflow`` must stay inert, and the
MLflow capability probe belongs to configure time. That prohibition costs this
module nothing: it reaches its stamp-time verdict through
:func:`semconv.operation_for_span`, which reads MLflow's attribute *names* as
transcribed string literals and imports no MLflow of its own.
"""

from collections.abc import Mapping

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

from . import _scope
from .eligibility import BILLABLE_GENAI_OPERATIONS
from .semconv import operation_for_span

__all__ = ["ReveniumAttributionSpanProcessor"]


def _declares_an_ineligible_operation(attributes: Mapping[str, object], /) -> bool:
    """The ``declared-only`` gate, in one comparison. See :meth:`.on_start`.

    Args:
        attributes: A live span's attributes, as they stand at ``on_start``.

    Returns:
        ``True`` only when the span *states* an operation and that operation is
        not billable. An unresolved operation returns ``False``: at ``on_start``
        it means undecided, not ineligible.

    **The resolution is delegated to :func:`semconv.operation_for_span` and never
    re-derived here.** That function is the single site in this package where the
    question "what operation did this span perform?" is answered —
    :func:`eligibility.classify_span` and :func:`semconv.map_span` both call it,
    which is what makes it impossible for a span to be admitted on one operation
    and rated under another (GAP-1). Calling it here adds a third *caller*, not a
    second predicate, so FB-05's claim that one source of truth decides
    eligibility stays exactly as true as it was.
    """
    operation = operation_for_span(attributes)
    return operation is not None and operation not in BILLABLE_GENAI_OPERATIONS


class ReveniumAttributionSpanProcessor(SpanProcessor):
    """Stamps Revenium attribution onto spans as they start.

    **Attribution is written in ``on_start`` and never in ``on_end`` (ATTR-02).**
    This is measured behaviour, not a stylistic preference: ``Span.end()``
    freezes the span's attributes before ``on_end`` is called, and ``on_end``
    receives an immutable ``ReadableSpan``. A write there is discarded, and
    MLflow suppresses the warning that would otherwise reveal it — so the
    mistake produces spans that export successfully and carry no attribution at
    all. ``tests/unit/test_on_start_not_on_end.py`` reproduces both halves of
    that in one process: the write through a retained live-span reference returns
    normally *and* the value is absent from the collected span.

    The class is public because the contract names it: an advanced user may
    register it on a tracer provider they own. :func:`configure_tracing`
    remains the supported entry point for everyone else.
    """

    def __init__(self) -> None:
        """Takes no arguments, and holds no state.

        The processor reads the scoped attribution from
        :mod:`revenium_mlflow.tracing._scope` on every span rather than holding a
        copy, so there is nothing to configure and nothing to keep in sync.
        Constructor-supplied *static* attribution — a value that applies to every
        span in the process regardless of scope — is ATTR-11 and belongs to plan
        03-05, which carries its own decision checkpoint precisely because adding
        a parameter here changes a signature Phase 1 already published.
        """

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Write the scoped attribution onto ``span``, subject to one gate.

        Args:
            span: The span OpenTelemetry has just created and not yet started
                recording into. Still mutable, which is the entire reason the
                write happens here.
            parent_context: The context the span was created under. Unused: the
                attribution this processor writes comes from the ``ContextVar``
                in effect on the current task, which is the same context the span
                was created under by construction.

        **The stamp-time rule, chosen by plan 03-01's ``checkpoint:decision``
        (``gate="blocking-human"``) and answered ``declared-only``:**

            Resolve the operation with :func:`semconv.operation_for_span`. Skip
            the stamp **only** when the result is not ``None`` *and* is not a
            member of :data:`eligibility.BILLABLE_GENAI_OPERATIONS`. An
            unresolved operation means undecided, and undecided is stamped.

        **Why the gate looks weak at this site, measured rather than assumed.**
        The obvious rule — consult :func:`eligibility.classify_span` and stamp
        only what it admits — cannot work here, and it fails silently rather than
        loudly. Measured against this repository's own ``.venv`` at MLflow
        3.16.0, across all three span-creation paths MLflow offers::

            path A: mlflow.start_span(span_type="CHAT_MODEL")
              on_start  mlflow.spanType='null'          classify_span -> WRONG_TYPE
              on_end    mlflow.spanType='"CHAT_MODEL"'  classify_span -> ADMITTED

            path B: @mlflow.trace(span_type="CHAT_MODEL")
              on_start  mlflow.spanType='null'          classify_span -> WRONG_TYPE
              on_end    mlflow.spanType='"CHAT_MODEL"'  classify_span -> ADMITTED

            path C: start_span_no_context(...)   <- autolog's child LLM spans
              on_start  mlflow.spanType='null'          classify_span -> WRONG_TYPE
              on_end    mlflow.spanType='"CHAT_MODEL"'  classify_span -> ADMITTED

        MLflow creates the OpenTelemetry span first — which is what fires
        ``on_start`` — and sets ``mlflow.spanType`` afterwards. Token counts
        arrive later still, at end. So at ``on_start`` both halves of the
        eligibility gate are undecidable, and ``classify_span`` returns
        ``WRONG_TYPE`` for every span in the process including genuinely billable
        ones. Gating on ``classify_span(span) is ADMITTED`` — or on
        ``classify_span(span) is not WRONG_TYPE``, which is the same mistake
        spelled defensively — therefore yields a processor that is installed,
        observes every span, stamps nothing, and reports no error. Do not
        reintroduce either spelling. ``tests/unit/test_stamp_time_evidence.py``
        pins this transcript against the installed MLflow, so a release that
        starts setting ``mlflow.spanType`` at creation time fails the build and
        returns the decision to whoever is here then, rather than quietly making
        this docstring wrong.

        **What the gate does buy.** One shape *is* decidable at ``on_start``: a
        span from a bridged non-MLflow OpenTelemetry instrumentor that sets a
        bare ``gen_ai.operation.name`` at creation. Such a span declaring
        ``execute_tool`` is rejected here and never carries
        ``revenium.subscriber.email`` at all.

        **What it does not buy, recorded as an accepted consequence (T-03-03).**
        For a pure-MLflow application every span is stamped, orchestration spans
        included, so ``revenium.subscriber.email`` reaches spans in the
        customer's *own* Tracking Server and their own OTLP collector. Nothing
        about billing follows from that: no orchestration span is exported to
        Revenium or metered as a completion, because the eligibility filter lives
        in the exporter pipeline (EXP-02) where the span is complete and
        ``classify_span`` returns a real verdict. SEM-11 is enforced at the export
        boundary, not here.

        **The empty-snapshot check runs first, and it is the hot path (T-03-05).**
        This method executes for every span in the host process, including in
        processes that never call :func:`attribution` at all. It does no I/O, no
        logging, no MLflow import, and it returns before resolving anything when
        there is no attribution to write.
        """
        snapshot = _scope.current()
        if not snapshot:
            return
        if _declares_an_ineligible_operation(span.attributes or {}):
            return
        for key, value in _scope.resolve_attributes(snapshot).items():
            span.set_attribute(key, value)

    def on_end(self, span: ReadableSpan) -> None:
        """Deliberately empty, and asserted empty over this method's AST (03-06).

        Args:
            span: The finished span. Read nothing from it and write nothing to
                it.

        This body is a docstring and nothing else, on purpose. ``Span.end()``
        freezes the attribute store before this is called and hands over an
        immutable ``ReadableSpan``, so an attribute write here is lost — either
        loudly, if attempted through this ``span`` argument, which has no
        ``set_attribute`` at all; or **silently**, if attempted through a live
        span reference retained from :meth:`on_start`, which does have the method
        and discards the write. The silent form is the realistic mistake and the
        one that survives review, which is why ``tests/unit/test_on_start_not_on_end.py``
        asserts both that it does not raise and that the value never arrives.
        Plan 03-06 walks the AST of this exact method and fails the build on any
        call that writes an attribute, so this emptiness is a checked property
        rather than a convention.
        """

    def shutdown(self) -> None:
        """Nothing to shut down.

        This processor owns no queue, no worker thread and no exporter — it
        mutates spans in place on the calling thread and returns. The conformant
        no-op is spelled out rather than inherited so that "there is nothing to
        flush" reads as a decision instead of an omission.
        """

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Nothing to flush; always succeeds.

        Args:
            timeout_millis: Ignored. There is no pending work to bound.

        Returns:
            ``True``, always. Returning ``False`` would tell a caller that a
            flush timed out, and this processor cannot time out because it never
            defers work.
        """
        return True
