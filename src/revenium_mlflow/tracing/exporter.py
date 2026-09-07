"""The export pipeline: filter, translate, carry attribution, claim the resource, delegate.

This is where the phase-2 pure functions meet a socket. Nothing in
:mod:`revenium_mlflow.tracing.eligibility` or
:mod:`revenium_mlflow.tracing.semconv` knows anything about OTLP; nothing here
re-derives a verdict or a mapping. The whole module is a composition, and the
ordering of that composition is the behaviour (EXP-02):

    filter -> translate -> validate caps -> redact -> merge resource -> delegate

**Why the eligibility filter lives here and not in the processor.** Plan 03-01's
``checkpoint:decision`` was answered ``declared-only``, which means orchestration
spans **are** stamped with ``revenium.*`` at ``on_start``. That was the only rule
that could work: MLflow sets ``mlflow.spanType`` *after* creating the
OpenTelemetry span, so at ``on_start`` ``classify_span`` returns ``WRONG_TYPE``
for every span in the process, billable ones included. By the time a span reaches
this exporter it is complete and the verdict is real. SEM-11 is therefore
enforced here or it is not enforced anywhere, and a ``CHAIN`` span reaching
Revenium is not a stray log line — it carries the aggregate of the model spans
nested inside it, so exporting it bills the same tokens twice.

**Why the span is rebuilt rather than mutated.** MLflow's own processor has
already exported this span object to the customer's Tracking Server by the time
the batch processor hands it here. Mutating it would reach back into a record
somebody else already owns. The reconstruction is a new
:class:`~opentelemetry.sdk.trace.ReadableSpan` carrying only what Revenium rates
on, and ``mlflow.get_trace()`` returns the same span count with and without this
SDK installed (T-04-04).

**Why attribution has to be carried forward explicitly.**
``semconv.EMITTED_ATTRIBUTE_KEYS`` is a closed fourteen-key allowlist and
``map_span`` filters its output against it. **No ``revenium.*`` key is in that
set.** A reconstruction built from ``mapped.attributes`` alone would therefore
export a perfectly semconv-correct span that Revenium cannot attribute to
anybody — a billing event with no customer, which fails silently at both ends.
The carry-forward reads :data:`~revenium_mlflow.attributes.REVENIUM_ATTRIBUTE_KEYS`,
the closed twenty-one-key set, rather than scanning for a ``revenium.`` prefix:
a prefix scan would forward whatever an application happened to name that way.

**What the exported resource says this SDK is — a recorded human decision.**
Plan 04-01 Task 1 was a ``checkpoint:decision`` with ``gate="blocking-human"``,
answered ``recommended`` on 2026-09-07. MLflow builds its resource with
``telemetry.sdk.name = "mlflow"``. PROJECT.md records that Revenium's
``GenAISemanticConventionMapper.canHandle`` **rejects** payloads whose SDK name
is in ``KNOWN_CUSTOM_SDK_NAMES``, and the contents of that set cannot be
established from inside this repository — PROJECT.md forbids calling
``api.revenium.io``. A non-claim is invisible on both sides: the spans arrive,
nothing is rated, and no error appears anywhere. The override removes that risk
rather than accepting it.

The accepted cost, recorded because it was accepted rather than overlooked:
"these spans came from MLflow" is no longer a resource-level fact. It stays
recoverable from two places, and **both are preserved deliberately** — the
reconstructed span carries the source span's own ``instrumentation_scope``
(``mlflow.tracing.provider``), and every span carries
``revenium.middleware.source = mlflow`` from the phase-3 stamp. Those two are now
the provenance path. Do not drop either as redundant.

This module imports no MLflow, at module scope or anywhere else (D-05).
"""

from collections.abc import Mapping as _Mapping
from collections.abc import Sequence as _Sequence
from typing import Final as _Final

from opentelemetry.sdk.resources import Resource as _Resource
from opentelemetry.sdk.trace import ReadableSpan as _ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter as _SpanExporter
from opentelemetry.sdk.trace.export import SpanExportResult as _SpanExportResult
from opentelemetry.util.types import AttributeValue as _AttributeValue

from revenium_mlflow.attributes import REVENIUM_ATTRIBUTE_KEYS as _REVENIUM_ATTRIBUTE_KEYS

from .eligibility import is_billable_llm_span as _is_billable_llm_span
from .semconv import RESOURCE_PROVIDER_CLAIM as _RESOURCE_PROVIDER_CLAIM
from .semconv import map_span as _map_span
from .semconv import resource_claim_attributes as _resource_claim_attributes

__all__ = ["ReveniumSpanExporter"]

#: The OpenTelemetry resource attribute naming the producing SDK. Overridden
#: rather than inherited — see this module's docstring for the decision and its
#: accepted cost.
_TELEMETRY_SDK_NAME: _Final[str] = "telemetry.sdk.name"


def _resource_overlay() -> _Resource:
    """The attributes this SDK writes over MLflow's resource, as a ``Resource``.

    Built through the ``Resource(attributes=...)`` constructor and **never**
    through ``Resource.create``. ``create`` runs OpenTelemetry's environment
    detectors and merges the default resource, which injects a ``service.name``
    nobody asked for — a resource attribute this SDK did not decide to send,
    arriving on a customer's billing payload.

    The provider claim comes from :func:`semconv.resource_claim_attributes`
    rather than from a literal here, so the value the resource claims and the
    value the spans claim are the same string in one place.

    **Open, and deliberately not closed here: ``telemetry.sdk.version``.** With
    the name overridden and the version inherited, the exported resource reads
    ``telemetry.sdk.name = "revenium-mlflow-sdk"`` alongside
    ``telemetry.sdk.version = "3.16.0"`` — MLflow's version, under this SDK's
    name, a pairing that is false and that this SDK has never shipped. Captured
    in ``docs/verification/exp-03-dual-export.md`` §5. It is left alone rather
    than quietly corrected because ``telemetry.sdk.version`` is a second
    wire-facing value reaching a live Revenium endpoint, and plan 04-01 Task 1
    made exactly that class of choice a ``gate="blocking-human"`` checkpoint. The
    obvious fix is ``revenium_mlflow.__version__``; making it without review
    would be the unreviewed wire change the checkpoint exists to prevent. A later
    plan in this phase should put it to a human.
    """
    attributes: dict[str, str] = dict(_resource_claim_attributes())
    attributes[_TELEMETRY_SDK_NAME] = _RESOURCE_PROVIDER_CLAIM
    return _Resource(attributes=attributes)


def _carried_attribution(span: _ReadableSpan, /) -> dict[str, _AttributeValue]:
    """The ``revenium.*`` attribution the phase-3 processor stamped, read off the source span.

    Args:
        span: The completed span, still carrying whatever ``on_start`` wrote.

    Returns:
        Only keys in :data:`~revenium_mlflow.attributes.REVENIUM_ATTRIBUTE_KEYS`,
        and only those actually present. A closed set rather than a
        ``startswith("revenium.")`` scan: the prefix form would forward any key
        an application happened to name that way, which is the open-ended shape
        the emit allowlist exists to prevent one layer down.
    """
    source: _Mapping[str, object] = span.attributes or {}
    carried: dict[str, _AttributeValue] = {}
    for key in _REVENIUM_ATTRIBUTE_KEYS:
        value = source.get(key)
        if isinstance(value, (str, bool, int, float)):
            carried[key] = value
    return carried


def _validate_caps(attributes: dict[str, _AttributeValue], /) -> dict[str, _AttributeValue]:
    """Seam for the ATTR-09 / EXP-02 cap check. Passes everything through today.

    **This is a named call site, not behaviour, and plan 04-05 fills it in.**
    It exists now because a seam is fillable without an architectural change,
    whereas inventing cap semantics here would collide with the plan that owns
    them — Revenium's per-column caps are the subject of that plan's own
    evidence, and a guess made here would have to be unmade there.
    """
    return attributes


def _redact(attributes: dict[str, _AttributeValue], /) -> dict[str, _AttributeValue]:
    """Seam for the EXP-02 redaction stage. Passes everything through today.

    Plan 04-05 fills this in, for the same reason :func:`_validate_caps` is a
    seam. Note what already limits exposure without it: ``map_span`` filters its
    output against the closed fourteen-key allowlist, this exporter forwards no
    span events at all — so no exception message or stack trace reaches the wire,
    only the ``error.type`` ``map_span`` derived from it — and the attribution
    carry-forward reads a closed twenty-one-key set. Redaction narrows values
    inside those keys; it is not the thing keeping arbitrary keys out.
    """
    return attributes


class ReveniumSpanExporter(_SpanExporter):
    """Wraps a delegate exporter with the EXP-02 pipeline.

    The delegate is whatever actually speaks to the network — in production an
    ``OTLPSpanExporter`` constructed with an explicit endpoint and headers, in
    tests the same thing pointed at a loopback collector. This class opens no
    socket of its own and knows no URL, which is what lets the pipeline be tested
    without a provider and the transport be tested without the pipeline.
    """

    def __init__(
        self,
        delegate: _SpanExporter,
        *,
        environment: str | None = None,
        region: str | None = None,
    ) -> None:
        """Hold the delegate and the two optional deployment labels.

        Args:
            delegate: The exporter that puts bytes on the wire.
            environment: Emitted as ``deployment.environment.name`` when set.
            region: Emitted as ``cloud.region`` when set.

        ``environment`` and ``region`` are passed through to
        :func:`semconv.map_span` rather than stored as configuration, which is
        where D-C6 put them.
        """
        self._delegate = delegate
        self._environment = environment
        self._region = region

    def export(self, spans: _Sequence[_ReadableSpan]) -> _SpanExportResult:
        """Run the pipeline over ``spans`` and hand the survivors to the delegate.

        Args:
            spans: One batch, as ``BatchSpanProcessor`` assembled it. Mixed:
                orchestration spans, billable model spans, and anything else the
                host process produced.

        Returns:
            The delegate's result, or ``SpanExportResult.SUCCESS`` when the
            filter admitted nothing.

        **An empty admitted set returns without touching the delegate.** A batch
        of pure orchestration spans is the common case in an agent framework, and
        it must cost no request at all — not an empty POST, which would put a
        credential on the wire to say nothing.
        """
        admitted = [span for span in spans if _is_billable_llm_span(span)]
        if not admitted:
            return _SpanExportResult.SUCCESS
        return self._delegate.export([self._rebuild(span) for span in admitted])

    def _rebuild(self, span: _ReadableSpan, /) -> _ReadableSpan:
        """One admitted span, translated into what Revenium rates on.

        Args:
            span: A span :func:`eligibility.is_billable_llm_span` admitted.

        Returns:
            A new ``ReadableSpan``. The source span is not touched — see this
            module's docstring for why (T-04-04).

        What is carried over from the source, and why each one:

        - ``context`` and ``parent``, so trace hierarchy survives and the
          backend can tell a root from a child.
        - ``instrumentation_scope``, which is ``mlflow.tracing.provider`` and is
          now part of the provenance path, since ``telemetry.sdk.name`` no longer
          says MLflow.
        - ``name`` and ``status``, which are neither billing inputs nor
          arbitrary application data.
        - the ``revenium.*`` attribution, which ``map_span`` does not forward.

        What is deliberately dropped: events and links. A span's ``exception``
        event carries a message and a stack trace, which are arbitrary
        application data and not in any allowlist — ``map_span`` already reads
        the one field of it that matters, ``exception.type``, and emits it as
        ``error.type``. Forwarding the event as well would put the payload back
        on the wire beside the summary of it.
        """
        mapped = _map_span(span, environment=self._environment, region=self._region)

        attributes: dict[str, _AttributeValue] = dict(mapped.attributes)
        attributes.update(_carried_attribution(span))
        attributes = _redact(_validate_caps(attributes))

        return _ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            # ``other`` wins in ``Resource.merge`` — the overlay is the argument,
            # not the receiver, and reversing this would silently restore
            # MLflow's ``telemetry.sdk.name`` and drop the provider claim.
            resource=span.resource.merge(_resource_overlay()),
            attributes=attributes,
            events=(),
            links=(),
            # SEM-12. A real captured MLflow CHAT_MODEL span is INTERNAL; the
            # GenAI conventions require CLIENT for inference, and the kind comes
            # from ``map_span`` rather than being restated here so it stays one
            # decision made in one place.
            kind=mapped.kind,
            instrumentation_scope=span.instrumentation_scope,
            status=span.status,
            # SEM-08: the mapped timings, which ``map_span`` read off the span's
            # own fields and already degraded for an unset or backwards clock.
            start_time=mapped.start_time_ns,
            end_time=mapped.end_time_ns,
        )

    def shutdown(self) -> None:
        """Shut the delegate down. This class owns no resource of its own."""
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush the delegate, bounded by ``timeout_millis``.

        Args:
            timeout_millis: The bound, in milliseconds, passed straight through.

        Returns:
            Whatever the delegate reported. Not coerced to ``True``: a flush that
            reports success it did not achieve is how a caller comes to believe
            telemetry was delivered when it was dropped.
        """
        return self._delegate.force_flush(timeout_millis)
