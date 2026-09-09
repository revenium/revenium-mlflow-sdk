"""The integration gate: one MLflow trace, two destinations, one process, one run.

This is the first test in the project that asserts on bytes that left the
process. Everything before it asserted on pure functions; everything after it
depends on this one being honest.

**Both destinations, or it proves nothing.** The claim Phase 4 exists to make is
not "Revenium received a span" and not "MLflow still works" — it is that *the
same trace* reached both, without the SDK diverting, replacing or double-counting
anything. So one fixture drives one span and then reads it back out of the MLflow
Tracking Server store *and* out of the fake collector's decoded protobuf.

**Why this is a ``unit`` test and not an ``integration`` one.** It stands up its
own collector socket and its own sqlite tracking store in-process and depends on
no running service. ``pyproject.toml`` sets ``addopts = -m 'not e2e and not
integration'``, so a gate test wearing the ``integration`` marker would be
excluded from ``scripts/check.sh`` — it would prove nothing on every run that
matters, which is the only kind of run there is.

**Why the fixture is module-scoped and never undone.**
``TracerProvider.add_span_processor`` appends and there is no public way to
detach. The bridged provider is global to the process, so attaching per test
would leave a growing stack of exporters pointed at collectors that had already
closed. ``tests/unit/test_stamp_time_evidence.py`` reaches the same conclusion
for the same reason. The batch processor *is* shut down on teardown, which is
what stops spans created by later test modules from queueing against a socket
that is no longer listening.

**No network.** The collector binds ``127.0.0.1`` on an ephemeral port, the
tracking store is a sqlite file under ``tmp_path``, and the only credential any
test supplies is the ``rev_mk_FAKE`` sentinel (T-04-03). ``test_every_export_was
_addressed_to_loopback`` asserts the negative directly off the captured requests.
"""

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from revenium_mlflow import ReveniumExportHandle, attribution, configure_tracing
from revenium_mlflow.tracing.processor import ReveniumAttributionSpanProcessor
from tests.fixtures.collector import ExportedSpan, FakeOTLPCollector

pytestmark = pytest.mark.unit

#: The sentinel credential. Never a live key, and shaped like the metering scope
#: so a reader can see which of the two credentials this path uses (T-04-03).
_FAKE_API_KEY = "rev_mk_FAKE"

#: The attribution the scope supplies. Read back off the decoded payload, which
#: is the only way to prove the phase-3 stamp survived the phase-4 boundary —
#: ``semconv.EMITTED_ATTRIBUTE_KEYS`` is a closed fourteen-key allowlist that
#: contains no ``revenium.*`` key at all, so the exporter has to carry these
#: forward deliberately or they vanish silently at the wire.
_SUBSCRIBER_ID = "sub-gate-01"
_ORGANIZATION_NAME = "org-gate-01"

#: The usage MLflow records on the span. ``cache_read_input_tokens`` is here
#: because MLflow's *own* native dual export drops it — measured, 900 sent and
#: only input/output delivered. Carrying it through this pipeline is a large part
#: of why this exporter exists rather than the env-var path.
_USAGE: Mapping[str, int] = {
    "input_tokens": 1000,
    "output_tokens": 50,
    "total_tokens": 1050,
    "cache_read_input_tokens": 900,
}

_BASELINE_SPAN = "baseline-chat"
_GATE_SPAN = "gate-chat"
_MIXED_ORCHESTRATION_SPAN = "mixed-chain"
_MIXED_BILLABLE_SPAN = "mixed-chat"

#: The OTLP ``SpanKind`` enum value for ``SPAN_KIND_CLIENT`` (SEM-12). Spelled
#: as the number the wire carries rather than as an SDK enum, because the claim
#: is about the encoded byte and not about what the SDK called it.
_SPAN_KIND_CLIENT = 3

#: MLflow's own instrumentation scope. Preserved on the reconstructed span on
#: purpose: with ``telemetry.sdk.name`` overridden to ``revenium-mlflow-sdk``
#: (plan 04-01 Task 1, answered ``recommended``), this and
#: ``revenium.middleware.source`` are the two surviving statements that these
#: spans came from MLflow.
_MLFLOW_SCOPE_NAME = "mlflow.tracing.provider"

#: The transcript this run is pinned against. Resolved from this file rather
#: than from the working directory, so the test means the same thing run from
#: anywhere.
_EVIDENCE_DOCUMENT = (
    Path(__file__).resolve().parents[2] / "docs" / "verification" / "exp-03-dual-export.md"
)


@dataclass(frozen=True)
class _Gate:
    """Everything one run of the fixture observed, captured once and asserted many times."""

    #: The handle ``configure_tracing`` returned.
    handle: ReveniumExportHandle

    #: Processor class names on the bridged provider, before and after configure.
    processors_before: tuple[str, ...]
    processors_after: tuple[str, ...]

    #: What ``handle.flush(5.0)`` returned for the billable trace.
    flush_result: bool

    #: The collector's captured requests for the billable trace, decoded.
    exported: tuple[ExportedSpan, ...]

    #: What ``FakeOTLPCollector.assert_received_export()`` said, or ``None`` when
    #: it was satisfied. Captured rather than raised so a pipeline that stopped
    #: exporting fails one named test loudly instead of erroring every test in
    #: this module with the same message.
    receipt_error: str | None

    #: The ``Host`` each captured request was addressed to, across every phase.
    hosts: tuple[str, ...]

    #: Content-Type of the billable trace's single export.
    content_type: str | None

    #: Whether the ``x-api-key`` header carried the sentinel, and whether any
    #: ``authorization`` header was sent at all. Both are Task 1's Q1 answer.
    api_key_header: str | None
    authorization_header: str | None

    #: Span counts read back out of the MLflow Tracking Server store.
    baseline_store_span_count: int
    gate_store_span_count: int
    mixed_store_span_count: int

    #: The spans the collector received for the mixed trace.
    mixed_exported: tuple[ExportedSpan, ...]


def _chat_span(mlflow: Any, name: str) -> str:
    """Create one MLflow ``CHAT_MODEL`` span carrying token usage. Returns its trace id."""
    with mlflow.start_span(name=name, span_type="CHAT_MODEL") as span:
        span.set_attribute("mlflow.llm.model", "gpt-4o")
        span.set_attribute("mlflow.llm.provider", "openai")
        span.set_attribute("mlflow.chat.tokenUsage", dict(_USAGE))
        trace_id: str = span.trace_id
    return trace_id


def _store_span_count(mlflow: Any, trace_id: str) -> int:
    """How many spans the Tracking Server store holds for ``trace_id``.

    ``flush_trace_async_logging`` first: MLflow logs traces on a background
    thread, and reading before it drains reports a trace that has not finished
    arriving. It does **not** flush the OpenTelemetry batch processor — that is
    ``handle.flush()``, and conflating the two is how an assertion ends up
    running before the POST it is asserting about.
    """
    mlflow.flush_trace_async_logging()
    trace = mlflow.get_trace(trace_id)
    assert trace is not None, f"the Tracking Server store returned nothing for {trace_id!r}"
    return len(trace.data.spans)


def _processor_names(provider: TracerProvider) -> tuple[str, ...]:
    """The class name of every processor attached to ``provider``.

    Reads OpenTelemetry's private ``_active_span_processor._span_processors``.
    That is sanctioned in tests and nowhere else: ``pyproject.toml`` exempts
    ``tests/**`` from ``SLF``, and ``src/revenium_mlflow`` is walked by
    ``tests/unit/test_private_access_wall.py`` precisely so this convenience
    cannot leak into the shipped package. There is no public accessor — the SDK
    itself answers "am I attached?" from the processor objects it holds on the
    handle rather than by reading this.
    """
    return tuple(
        type(processor).__name__ for processor in provider._active_span_processor._span_processors
    )


@pytest.fixture(scope="module")
def gate(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Gate]:
    """One configure call, three traces, and every observation this module asserts on.

    The sequence is fixed and each step depends on the one before it:

    1. A baseline trace **before** ``configure_tracing`` — the control for
       T-04-04's "MLflow's own export is unchanged" claim. Without it, "one span
       in the store" is a number with nothing to compare against.
    2. Configure, recording the processor list on either side of the call.
    3. The billable trace, inside an ``attribution()`` scope, then a bounded
       flush, then the capture.
    4. A mixed trace — an orchestration parent wrapping a billable child — which
       is where SEM-11's enforcement point is proven to be the exporter.
    """
    database = tmp_path_factory.mktemp("mlflow-dual-export") / "tracking.db"
    previous_uri = os.environ.get("MLFLOW_TRACKING_URI")
    os.environ["MLFLOW_TRACKING_URI"] = f"sqlite:///{database}"

    collector = FakeOTLPCollector()
    handle: ReveniumExportHandle | None = None
    try:
        with collector:
            import mlflow

            provider = mlflow.tracing.get_bridged_tracer_provider()
            processors_before = _processor_names(provider)

            baseline_trace_id = _chat_span(mlflow, _BASELINE_SPAN)
            baseline_count = _store_span_count(mlflow, baseline_trace_id)

            handle = configure_tracing(
                otlp_traces_endpoint=collector.endpoint,
                api_key=_FAKE_API_KEY,
            )
            processors_after = _processor_names(provider)

            collector.reset()
            with attribution(
                subscriber_id=_SUBSCRIBER_ID,
                organization_name=_ORGANIZATION_NAME,
            ):
                gate_trace_id = _chat_span(mlflow, _GATE_SPAN)
            flush_result = handle.flush(5.0)

            gate_requests = collector.requests
            try:
                collector.assert_received_export()
                receipt_error: str | None = None
            except AssertionError as failure:
                receipt_error = str(failure)
            gate_exported = tuple(collector.exported_spans())
            gate_count = _store_span_count(mlflow, gate_trace_id)

            collector.reset()
            with (
                attribution(subscriber_id=_SUBSCRIBER_ID),
                mlflow.start_span(name=_MIXED_ORCHESTRATION_SPAN, span_type="CHAIN") as parent,
            ):
                # The orchestration span carries token counts on purpose: it
                # is the aggregate of its children, which is exactly what
                # makes exporting it a double-count rather than a stray log
                # line. A CHAIN span with no tokens would be rejected for two
                # reasons at once and prove neither.
                parent.set_attribute("mlflow.chat.tokenUsage", dict(_USAGE))
                mixed_trace_id: str = parent.trace_id
                with mlflow.start_span(name=_MIXED_BILLABLE_SPAN, span_type="CHAT_MODEL") as child:
                    child.set_attribute("mlflow.llm.model", "gpt-4o")
                    child.set_attribute("mlflow.chat.tokenUsage", dict(_USAGE))
            handle.flush(5.0)
            mixed_exported = tuple(collector.exported_spans())
            mixed_count = _store_span_count(mlflow, mixed_trace_id)

            headers = gate_requests[0].headers if gate_requests else {}
            yield _Gate(
                handle=handle,
                processors_before=processors_before,
                processors_after=processors_after,
                flush_result=flush_result,
                exported=gate_exported,
                receipt_error=receipt_error,
                hosts=collector.hosts + tuple(request.host for request in gate_requests),
                content_type=headers.get("content-type"),
                api_key_header=headers.get("x-api-key"),
                authorization_header=headers.get("authorization"),
                baseline_store_span_count=baseline_count,
                gate_store_span_count=gate_count,
                mixed_store_span_count=mixed_count,
                mixed_exported=mixed_exported,
            )
    finally:
        # The processor stays attached to the process-global provider forever —
        # ``add_span_processor`` appends and there is no public way to detach —
        # so shutting it down is the only way to stop later test modules' MLflow
        # spans from queueing against a collector socket that has closed. Each
        # such span would otherwise wait out an export timeout.
        #
        # Reached through the private attribute deliberately. A public
        # ``ReveniumExportHandle.shutdown()`` would be new published surface, and
        # handle lifecycle belongs to plan 04-04; inventing it here as test
        # scaffolding would pre-empt that plan's decision with a convenience.
        if handle is not None:
            handle._batch_processor.shutdown()
        if previous_uri is None:
            os.environ.pop("MLFLOW_TRACKING_URI", None)
        else:
            os.environ["MLFLOW_TRACKING_URI"] = previous_uri


def test_the_collector_received_a_decodable_export(gate: _Gate) -> None:
    """The non-vacuity control, asserted before anything reads the payload.

    Every other test in this module is a statement about the *content* of an
    export, and a comprehension over an empty list satisfies all of them at once.
    This one fails when nothing arrived. Plan 04-01 Task 3 proves it can fail by
    removing the exporter's delegate call and capturing the red.
    """
    assert gate.receipt_error is None, gate.receipt_error
    assert gate.exported, (
        "the collector captured no spans for the billable trace. Nothing else in "
        "this module is evidence of an export."
    )


def test_configure_tracing_returns_a_typed_handle(gate: _Gate) -> None:
    """CFG-07: never ``None``. A configure call that returns nothing leaves an
    operator with no way to answer "is it actually installed?"."""
    assert isinstance(gate.handle, ReveniumExportHandle)


def test_flush_drained_the_queue_within_its_bound(gate: _Gate) -> None:
    """T-04-05: bounded, and it reports whether it drained rather than assuming it did."""
    assert gate.flush_result is True


def test_both_processors_were_attached_and_neither_was_there_before(gate: _Gate) -> None:
    """The attach point worked, and the two names are new rather than pre-existing.

    Asserting the delta rather than the presence: MLflow's own
    ``MlflowV3SpanProcessor`` is already on the provider, and a test that only
    checked "a BatchSpanProcessor is attached" would pass against an MLflow that
    had attached one itself.
    """
    added = [name for name in gate.processors_after if name not in gate.processors_before]
    assert ReveniumAttributionSpanProcessor.__name__ in added
    assert BatchSpanProcessor.__name__ in added


def test_the_attribution_processor_is_registered_before_the_batch_processor(
    gate: _Gate,
) -> None:
    """Registration order is invocation order, and the stamp has to land first.

    OpenTelemetry invokes processors in the order they were added. A stamp
    written after the batch processor has already taken the span is a stamp
    nobody exported — and it fails silently, because the export still succeeds.
    """
    names = list(gate.processors_after)
    assert names.index(ReveniumAttributionSpanProcessor.__name__) < names.index(
        BatchSpanProcessor.__name__
    )


def test_the_export_was_protobuf_over_http(gate: _Gate) -> None:
    """CFG-09. MLflow's own default is grpc; falling through to it is what this prevents."""
    assert gate.content_type == "application/x-protobuf"


def test_the_credential_rode_on_x_api_key_and_nowhere_else(gate: _Gate) -> None:
    """Plan 04-01 Task 1 Q1, answered ``recommended`` by a human on 2026-09-07.

    Lowercase ``x-api-key``, matching all six ``/meter/*`` call sites in the
    installed ``revenium-python-sdk`` 0.7.0 wheel. **Only** that header: an
    ``Authorization: Bearer`` sent alongside would double the number of places
    the credential appears in any captured traffic, log or proxy record, which is
    the cost the ``both-headers`` option was rejected for.
    """
    assert gate.api_key_header == _FAKE_API_KEY
    assert gate.authorization_header is None


def test_every_export_was_addressed_to_loopback(gate: _Gate) -> None:
    """T-04-02, asserted off the captured requests rather than off the fixture's source.

    A collector edited to bind a routable address fails here instead of
    exfiltrating. Reading the ``Host`` header means the assertion is about where
    the client sent the bytes, not about where the server intended to listen.
    """
    assert gate.hosts, "no request was captured, so this asserts nothing"
    assert set(gate.hosts) == {"127.0.0.1"}


def test_exactly_one_span_reached_revenium_for_the_billable_trace(gate: _Gate) -> None:
    """One model call, one exported span. The trace had exactly one span to begin with."""
    assert len(gate.exported) == 1


def test_the_exported_span_is_client_kind(gate: _Gate) -> None:
    """SEM-12. A raw MLflow ``CHAT_MODEL`` span is ``INTERNAL`` (1) on the wire;
    the GenAI conventions require ``CLIENT`` (3) for inference."""
    assert gate.exported[0].kind == _SPAN_KIND_CLIENT


def test_the_exported_span_is_translated_not_forwarded(gate: _Gate) -> None:
    """``gen_ai.operation.name`` is ``chat``, and no ``mlflow.*`` key survived.

    An untranslated MLflow span arrives carrying ``mlflow.traceRequestId``,
    ``mlflow.spanType``, ``mlflow.chat.tokenUsage`` and ``mlflow.spanLogLevel``.
    That is what MLflow's own OTLP path emits and what this exporter exists to
    replace, so the absence is as much the claim as the presence.
    """
    attributes = gate.exported[0].attributes
    assert attributes["gen_ai.operation.name"] == "chat"
    assert [key for key in attributes if key.startswith("mlflow.")] == []


def test_token_counts_arrived_as_integers_not_strings(gate: _Gate) -> None:
    """Asserted on the ``AnyValue`` oneof, not on the unwrapped Python value.

    ``isinstance(value, int)`` accepts a ``bool_value``, so the unwrapped value
    alone cannot distinguish "the backend can sum this" from "the backend gets a
    string it will drop". The oneof name can.
    """
    span = gate.exported[0]
    for key, expected in (
        ("gen_ai.usage.input_tokens", _USAGE["input_tokens"]),
        ("gen_ai.usage.output_tokens", _USAGE["output_tokens"]),
    ):
        assert span.attribute_kinds[key] == "int_value", (
            f"{key} arrived as {span.attribute_kinds[key]}"
        )
        assert span.attributes[key] == expected


def test_cache_read_tokens_survived_the_pipeline(gate: _Gate) -> None:
    """The measured loss in MLflow's own native dual export, absent here.

    Measured independently against MLflow 3.16.0: 900 ``cache_read_input_tokens``
    sent, only input and output delivered. A cached-read token is priced
    differently from a fresh one, so dropping it is a wrong invoice rather than a
    missing metric — and it is the concrete reason this SDK owns its exporter
    instead of setting ``MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT=true``.
    """
    span = gate.exported[0]
    assert span.attribute_kinds["gen_ai.usage.cache_read_input_tokens"] == "int_value"
    assert (
        span.attributes["gen_ai.usage.cache_read_input_tokens"]
        == (_USAGE["cache_read_input_tokens"])
    )


def test_the_phase_three_attribution_survived_the_export_boundary(gate: _Gate) -> None:
    """``revenium.*`` reaches the wire, which ``map_span`` alone would not achieve.

    ``semconv.EMITTED_ATTRIBUTE_KEYS`` is a closed fourteen-key allowlist and
    contains no attribution key, so a reconstruction that carried only the mapped
    attributes would export a perfectly semconv-correct span that Revenium cannot
    attribute to anybody. Both halves are asserted: the value the scope supplied,
    and the ``middleware.source`` default that is now part of the provenance path
    for these spans.
    """
    attributes = gate.exported[0].attributes
    assert attributes["revenium.subscriber.id"] == _SUBSCRIBER_ID
    assert attributes["revenium.organization.name"] == _ORGANIZATION_NAME
    assert attributes["revenium.middleware.source"] == "mlflow"


def test_the_resource_claims_the_provider(gate: _Gate) -> None:
    """SEM-02. MLflow's own resource carries nothing the backend's mapper can key on."""
    resource = gate.exported[0].resource_attributes
    assert resource["gen_ai.provider.name"] == "revenium-mlflow-sdk"
    assert resource["gen_ai.system"] == "revenium-mlflow-sdk"


def test_the_resource_sdk_name_was_overridden(gate: _Gate) -> None:
    """Plan 04-01 Task 1 Q2, answered ``recommended`` by a human on 2026-09-07.

    MLflow builds the resource with ``telemetry.sdk.name = "mlflow"``. PROJECT.md
    records that Revenium's ``GenAISemanticConventionMapper.canHandle`` rejects
    payloads whose SDK name is in ``KNOWN_CUSTOM_SDK_NAMES``, and the contents of
    that set are not knowable from inside this repository. A non-claim is
    invisible on both sides — the spans arrive and are never rated, with no error
    anywhere — so the override removes the risk rather than accepting it.
    """
    assert gate.exported[0].resource_attributes["telemetry.sdk.name"] == ("revenium-mlflow-sdk")


def test_the_instrumentation_scope_still_says_mlflow(gate: _Gate) -> None:
    """The accepted cost of the override, and the path that pays it back.

    Overriding ``telemetry.sdk.name`` gives up "these spans came from MLflow" as
    a resource-level fact. The human who answered Task 1 accepted that on the
    record because it stays recoverable from two other places, and this is one of
    them — the reconstructed span carries the source span's own instrumentation
    scope rather than a fresh one. ``revenium.middleware.source = mlflow`` is the
    other, asserted above.
    """
    assert gate.exported[0].scope_name == _MLFLOW_SCOPE_NAME


def test_the_same_trace_is_readable_from_the_tracking_server_store(gate: _Gate) -> None:
    """The other destination. "Dual" is the outcome, and this is the half that is not Revenium."""
    assert gate.gate_store_span_count == 1


def test_mlflows_own_export_is_unchanged_by_configuring(gate: _Gate) -> None:
    """T-04-04: the span count in the store is the same with and without the SDK.

    The exported span is *rebuilt*, never mutated, so the object MLflow's own
    processor already exported is never touched. The baseline trace ran before
    ``configure_tracing`` and is the control — without it this is a number
    with nothing to compare against.
    """
    assert gate.gate_store_span_count == gate.baseline_store_span_count


def test_the_orchestration_span_reached_mlflow_but_not_revenium(gate: _Gate) -> None:
    """SEM-11, enforced where it is enforceable, asserted by inspection not by counting.

    Phase 3's ``declared-only`` stamp rule means orchestration spans **are**
    stamped with ``revenium.*`` at ``on_start`` — that was a human-answered
    checkpoint with T-03-03 accepted on the record. The eligibility filter in
    this exporter is therefore the only thing standing between a CHAIN span and a
    Revenium invoice, and a CHAIN span carrying the aggregate of its children is
    a double-count.

    Every decoded span is inspected rather than counted: a count of one is also
    satisfied by a payload containing the orchestration span and *not* the
    billable one, which would be the same bug with the opposite sign.
    """
    assert gate.mixed_store_span_count == 2, (
        "the customer's own Tracking Server must still receive both spans"
    )
    operations = [span.attributes.get("gen_ai.operation.name") for span in gate.mixed_exported]
    assert operations == ["chat"], (
        f"expected exactly the billable span to reach Revenium, got operations {operations} "
        f"from span names {[span.name for span in gate.mixed_exported]}"
    )
    assert [span.name for span in gate.mixed_exported] == [_MIXED_BILLABLE_SPAN]


def _evidence_lines(gate: _Gate) -> list[str]:
    """The facts this run measured, one per line, in the form the transcript carries.

    Derived from the ``gate`` fixture rather than re-measured, so the document and
    the assertions in this module are pinned to the *same* run. Values that carry
    a wire encoding are rendered with their ``AnyValue`` oneof in parentheses:
    "1000" and "1000 (int_value)" are different claims, and only the second one
    is about the bytes.
    """
    import mlflow
    from opentelemetry.sdk.version import __version__ as otel_sdk_version

    span = gate.exported[0]

    def attribute(key: str) -> str:
        return f"span {key} = {span.attributes[key]} ({span.attribute_kinds[key]})"

    return [
        f"mlflow.__version__ = {mlflow.__version__}",
        f"opentelemetry-sdk = {otel_sdk_version}",
        f"store spans without configure_tracing = {gate.baseline_store_span_count}",
        f"store spans for the gate trace = {gate.gate_store_span_count}",
        f"store spans for the mixed trace = {gate.mixed_store_span_count}",
        f"exported spans for the gate trace = {len(gate.exported)}",
        f"exported spans for the mixed trace = {len(gate.mixed_exported)}",
        f"content-type = {gate.content_type}",
        f"x-api-key = {gate.api_key_header}",
        f"authorization = {gate.authorization_header}",
        f"host = {gate.hosts[0]}",
        f"span kind = {span.kind}",
        f"instrumentation scope = {span.scope_name}",
        f"resource telemetry.sdk.name = {span.resource_attributes['telemetry.sdk.name']}",
        f"resource gen_ai.provider.name = {span.resource_attributes['gen_ai.provider.name']}",
        f"resource gen_ai.system = {span.resource_attributes['gen_ai.system']}",
        attribute("gen_ai.operation.name"),
        attribute("gen_ai.provider.name"),
        attribute("gen_ai.request.model"),
        attribute("gen_ai.usage.input_tokens"),
        attribute("gen_ai.usage.output_tokens"),
        attribute("gen_ai.usage.cache_read_input_tokens"),
        attribute("revenium.subscriber.id"),
        attribute("revenium.organization.name"),
        attribute("revenium.middleware.source"),
        f"mixed trace exported span names = {[s.name for s in gate.mixed_exported]}",
    ]


def test_the_verification_document_records_what_this_run_measured(gate: _Gate) -> None:
    """``docs/verification/exp-03-dual-export.md`` and this run stay one fact.

    This project's evidence constraint requires command output behind a claim,
    and that document carries it. A checked-in transcript rots the moment someone
    upgrades MLflow or OpenTelemetry, and a rotted transcript is worse than none:
    it reads as current evidence for a measurement nobody re-ran. The same
    circularity gets the same treatment in ``tests/unit/test_stamp_time_evidence.py``
    and ``tests/unit/test_semconv_cache_tokens.py``.

    Whitespace is collapsed on both sides before comparison. The document formats
    its dump for a human reader, and the formatting is not the fact.
    """
    document = _EVIDENCE_DOCUMENT.read_text(encoding="utf-8")
    collapsed = " ".join(document.split())

    missing = [line for line in _evidence_lines(gate) if " ".join(line.split()) not in collapsed]
    assert missing == [], (
        f"{_EVIDENCE_DOCUMENT.name} no longer records what this run measured. "
        f"Absent from it: {missing}. Re-run the reproducer in its section 3 and paste "
        "the new output, rather than editing the dump by hand."
    )
