"""EXP-02, driven directly: the pipeline, without a provider and without MLflow.

``tests/unit/test_dual_export_gate.py`` proves the whole path works end to end.
This module proves *which layer* does what, by driving
:class:`~revenium_mlflow.tracing.exporter.ReveniumSpanExporter` with hand-built
spans from ``tests/fixtures/spans.py`` and reading the result off the same fake
collector. There is no tracer provider here, no MLflow import, and no batch
processor — so a failure localises to the pipeline instead of to any of the three
other things the gate test has running at once.

**The load-bearing test in this file is the orchestration one.** Plan 03-01's
``checkpoint:decision`` was answered ``declared-only`` with T-03-03 accepted on
the record, which means orchestration spans **are** stamped with ``revenium.*``
at ``on_start``. The eligibility filter in this exporter is the only thing
standing between a ``CHAIN`` span and a Revenium invoice, and a ``CHAIN`` span
carries the aggregate of the model spans nested inside it — exporting it bills
the same tokens twice. SEM-11 is enforced here or it is not enforced. Both this
assertion and the collector's own receipt check were shown red under sabotage and
then restored; the transcripts are in ``docs/verification/exp-03-dual-export.md``
and this module's last test pins that document to a live run.

The delegate is a real ``OTLPSpanExporter`` pointed at the loopback collector,
not a stub. A stub delegate would let every assertion below be made about a
Python object this test handed to itself, which is the exact failure shape VER-03
exists to close.
"""

from collections.abc import Iterator, Sequence

import pytest
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult

from revenium_mlflow.tracing.exporter import ReveniumSpanExporter
from tests.fixtures.collector import ExportedSpan, FakeOTLPCollector
from tests.fixtures.spans import (
    anthropic_cache_span,
    mlflow_chat_model_span,
    openai_autolog_shaped_span,
    orchestration_span,
)

pytestmark = pytest.mark.unit

#: The sentinel credential, never a live key (T-04-03).
_FAKE_API_KEY = "rev_mk_FAKE"

#: The OTLP ``SpanKind`` value for ``SPAN_KIND_CLIENT`` (SEM-12).
_SPAN_KIND_CLIENT = 3

#: The four orchestration span types. None of them resolves to a billable
#: operation, so none should ever appear in a decoded payload.
_ORCHESTRATION_TYPES = ("CHAIN", "AGENT", "TOOL", "RETRIEVER")


@pytest.fixture
def collector() -> Iterator[FakeOTLPCollector]:
    """A fresh loopback collector per test, torn down after it."""
    with FakeOTLPCollector() as running:
        yield running


@pytest.fixture
def exporter(collector: FakeOTLPCollector) -> Iterator[ReveniumSpanExporter]:
    """The pipeline, wrapping a real OTLP HTTP exporter pointed at ``collector``.

    Synchronous: ``SpanExporter.export`` blocks until the POST completes, so
    nothing in this module needs a flush. That is the other reason to drive the
    exporter directly rather than through a ``BatchSpanProcessor`` — a batching
    layer would put a queue between the assertion and the fact.
    """
    delegate = OTLPSpanExporter(
        endpoint=collector.endpoint,
        headers={"x-api-key": _FAKE_API_KEY},
        timeout=5,
    )
    wrapped = ReveniumSpanExporter(delegate)
    try:
        yield wrapped
    finally:
        wrapped.shutdown()


def _export(
    exporter: ReveniumSpanExporter,
    collector: FakeOTLPCollector,
    spans: Sequence[ReadableSpan],
) -> list[ExportedSpan]:
    """Export ``spans`` and return what the collector decoded, asserting success first."""
    assert exporter.export(spans) is SpanExportResult.SUCCESS
    return collector.exported_spans()


def test_a_billable_span_reaches_the_collector_translated(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """The baseline the rest of this module is a variation on.

    Also the non-vacuity control for every negative assertion below: without it,
    "no orchestration span arrived" would be satisfied by a pipeline that
    exported nothing at all.
    """
    (exported,) = _export(exporter, collector, [mlflow_chat_model_span()])
    assert exported.attributes["gen_ai.operation.name"] == "chat"
    assert exported.kind == _SPAN_KIND_CLIENT
    assert exported.resource_attributes["gen_ai.provider.name"] == "revenium-mlflow-sdk"


def test_a_mixed_batch_exports_only_its_billable_span(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """SEM-11, asserted by inspecting every decoded span rather than by counting.

    A count of one is also satisfied by a payload holding the orchestration span
    and *not* the model span — the same bug with the opposite sign. So every
    decoded span is checked against the billable operation set, and the
    orchestration type is separately confirmed absent.
    """
    exported = _export(
        exporter,
        collector,
        [orchestration_span(), mlflow_chat_model_span(), orchestration_span(span_type="AGENT")],
    )
    operations = [span.attributes.get("gen_ai.operation.name") for span in exported]
    assert operations == ["chat"], (
        f"expected only the billable span to reach the collector, decoded {operations}"
    )
    assert all("mlflow.spanType" not in span.attributes for span in exported)


@pytest.mark.parametrize("span_type", _ORCHESTRATION_TYPES)
def test_a_batch_of_only_orchestration_spans_produces_no_request_at_all(
    span_type: str, exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """No admitted span means no delegate call, not an empty POST.

    An agent framework produces batches like this constantly. An empty export
    would put a credential on the wire to say nothing, once per batch, forever.
    Asserted on the collector's captured-request list rather than on the return
    value, so it is a statement about the socket.
    """
    assert exporter.export([orchestration_span(span_type=span_type)]) is SpanExportResult.SUCCESS
    assert collector.requests == ()


def test_an_orchestration_span_carrying_tokens_is_still_rejected(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """The type gate runs before the token gate, and this is why that ordering matters.

    ``orchestration_span`` carries the same usage mapping the billable fixture
    does — deliberately, because without token counts a CHAIN span would be
    rejected for two reasons at once and this test could not tell which one
    fired. Those tokens are the aggregate of the children; admitting the span on
    them is the double-count.
    """
    assert exporter.export([orchestration_span()]) is SpanExportResult.SUCCESS
    assert collector.requests == ()


def test_a_span_with_no_provider_attribute_still_exports_a_named_provider(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """SEM-01/D-13: never empty, even when MLflow's OpenAI path writes nothing.

    ``mlflow/openai/autolog.py`` never sets ``mlflow.llm.provider``; the
    Anthropic path does. The provider is therefore inferred, and the span-level
    value and the resource-level claim are asserted to be independent facts — the
    resource claim is about this SDK, the span value is about the traffic, and a
    pipeline that conflated them would report every call as coming from Revenium.
    """
    (exported,) = _export(exporter, collector, [openai_autolog_shaped_span()])
    assert exported.attributes["gen_ai.provider.name"] == "openai"
    assert exported.attributes["gen_ai.system"] == "openai"
    assert exported.resource_attributes["gen_ai.provider.name"] == "revenium-mlflow-sdk"


def test_both_cache_token_keys_reach_the_wire_as_integers(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """The keys MLflow's own translator drops, present here and integer-encoded.

    Measured independently against MLflow 3.16.0: its native dual export
    delivered ``input_tokens`` and ``output_tokens`` and dropped
    ``cache_read_input_tokens`` entirely. A cached read is priced differently
    from a fresh one, so the drop is a wrong invoice rather than a missing
    metric. Asserted on the ``AnyValue`` oneof because a count that arrived as a
    ``string_value`` would satisfy an equality check against ``"3"`` and be
    unsummable at the far end.
    """
    (exported,) = _export(
        exporter, collector, [anthropic_cache_span(cache_read=3, cache_creation=2)]
    )
    for key, expected in (
        ("gen_ai.usage.cache_read_input_tokens", 3),
        ("gen_ai.usage.cache_creation_input_tokens", 2),
    ):
        assert exported.attribute_kinds[key] == "int_value", (
            f"{key} arrived as {exported.attribute_kinds[key]}"
        )
        assert exported.attributes[key] == expected


def test_the_source_spans_instrumentation_scope_survives_reconstruction(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """Half the provenance path that pays for the ``telemetry.sdk.name`` override.

    Plan 04-01 Task 1 was answered ``recommended``: the resource no longer says
    MLflow. The human accepted that on the record because the fact stays
    recoverable — from this scope, and from ``revenium.middleware.source``. Both
    are load-bearing now, so both are asserted rather than assumed.
    """
    (exported,) = _export(exporter, collector, [mlflow_chat_model_span()])
    assert exported.scope_name == "mlflow.tracing.provider"


def test_the_source_span_is_not_mutated_by_being_exported(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """T-04-04: the span is rebuilt, so MLflow's own record is never touched.

    MLflow's processor has already exported this object to the customer's
    Tracking Server by the time the batch processor hands it here. Asserted on
    the source object directly — the gate test asserts the same property from the
    other side, by reading the span count back out of the store.
    """
    source = mlflow_chat_model_span()
    before = dict(source.attributes or {})
    _export(exporter, collector, [source])
    assert dict(source.attributes or {}) == before
    assert source.kind.name == "INTERNAL"


def test_no_span_event_reaches_the_wire(
    exporter: ReveniumSpanExporter, collector: FakeOTLPCollector
) -> None:
    """Events are dropped deliberately, and the summary of them is not.

    An ``exception`` event carries a message and a stack trace, which are
    arbitrary application data in no allowlist. ``map_span`` already reads the
    one field that matters and emits it as ``error.type``, so forwarding the
    event as well would put the payload back on the wire beside the summary of
    it. Asserted through the decoded protobuf's own span, whose ``events`` list
    is empty.
    """
    exporter.export([mlflow_chat_model_span()])
    (decoded,) = collector.decoded()
    spans = [
        span
        for resource_spans in decoded.resource_spans
        for scope_spans in resource_spans.scope_spans
        for span in scope_spans.spans
    ]
    assert [list(span.events) for span in spans] == [[]]
